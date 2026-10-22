#!/usr/bin/env python3
"""Throwaway GPU pod on AWS EC2 for ingestion (DECISIONS.md §2 and §12).

One g6e.xlarge (1x L40S, 48 GB) on-demand, Deep Learning Base AMI, vLLM
serving an open-weight model on the pod's localhost. Copyrighted text goes
up over SSH, the pack comes back over SSH, and the instance and its disk are
destroyed afterwards.

Safety rails:
- The instance shuts itself down after --max-hours, and shutdown means
  *terminate* (the root volume is deleted on termination). A crashed laptop
  cannot leave a GPU running.
- SSH (port 22) is open only to your current public IP. vLLM's port is not
  opened at all: reach it through an SSH tunnel (`ssh` subcommand, -L).
- IMDSv2 required, encrypted root volume, no instance profile (no AWS
  credentials on the pod).
- Every resource is tagged `tome:pod=<name>`, so `down` finds and removes
  the instance, its security group and its key pair without local state.

Uses the AWS CLI (already set up per MAC_SETUP.md), ssh and rsync. The region
is the AWS CLI's (`aws configure get region`, or AWS_REGION / --region).

Usage:
  uv run scripts/gpu_pod.py up                       # launch, wait for SSH
  uv run scripts/gpu_pod.py setup                    # copy code, install uv, tome and vLLM
  uv run scripts/gpu_pod.py vllm --model Qwen/Qwen2.5-14B-Instruct
  uv run scripts/gpu_pod.py push library/harry-potter.epub library/series/harry-potter.toml
  uv run scripts/gpu_pod.py exec -- uv run tome pack build-text library/harry-potter.epub ...
  uv run scripts/gpu_pod.py pull data/harry-potter.tome
  uv run scripts/gpu_pod.py down                     # terminate + delete SG and key pair
  uv run scripts/gpu_pod.py status
  uv run scripts/gpu_pod.py ssh [-- -L 8000:localhost:8000]

  # All of it in one go; `down` runs even if a step fails (unless --keep):
  uv run scripts/gpu_pod.py run --model Qwen/Qwen2.5-14B-Instruct \\
      --push library/harry-potter.epub --push library/series/harry-potter.toml \\
      --pull data/harry-potter.tome -- uv run tome pack build-text ...

HF_TOKEN (for gated models) is forwarded over SSH from your environment when
set; it is never put in user data, which the instance metadata service exposes.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / ".cache" / "gpu-pod"  # gitignored; holds the private SSH key
TAG = "tome:pod"

INSTANCE_TYPE = "g6e.xlarge"
# Driver + CUDA, no framework: vLLM brings its own PyTorch.
AMI_NAME = "Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04) *"
SSH_USER = "ubuntu"
ROOT_VOLUME_GB = 200  # ~40 GB for a 70B 4-bit model, plus vLLM and the HF cache
VLLM_VERSION = "0.11.0"
VLLM_PORT = 8000  # matches the vllm-local provider preset
REMOTE_DIR = "tome"  # under the ubuntu user's home

# Local paths never copied to the pod by `setup` (book text goes up only via `push`).
RSYNC_EXCLUDES = [
    ".git",
    ".venv",
    ".cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".DS_Store",
    "library",
    "data",
    "corpus",
]


# --- helpers -----------------------------------------------------------------


def log(msg: str) -> None:
    print(f"[gpu-pod] {msg}", file=sys.stderr, flush=True)


def aws(args: argparse.Namespace, *cmd: str, check: bool = True) -> dict | list | None:
    full = ["aws", *cmd, "--output", "json"]
    if args.region:
        full += ["--region", args.region]
    if args.profile:
        full += ["--profile", args.profile]
    p = subprocess.run(full, capture_output=True, text=True)
    if p.returncode != 0:
        if check:
            sys.exit(f"aws {' '.join(cmd[:2])} failed:\n{p.stderr.strip()}")
        aws.last_error = p.stderr.strip()
        return None
    return json.loads(p.stdout) if p.stdout.strip() else None


def region(args: argparse.Namespace) -> str:
    if args.region:
        return args.region
    cmd = ["aws", "configure", "get", "region"]
    if args.profile:
        cmd += ["--profile", args.profile]
    r = os.environ.get("AWS_REGION") or subprocess.run(cmd, capture_output=True, text=True).stdout
    if not r.strip():
        sys.exit("no AWS region configured; pass --region or set one with `aws configure`")
    return r.strip()


def my_ip() -> str:
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10) as r:
        return r.read().decode().strip()


def key_path(name: str) -> Path:
    return STATE_DIR / f"{name}.pem"


def find_instance(args: argparse.Namespace) -> dict | None:
    out = aws(
        args,
        "ec2",
        "describe-instances",
        "--filters",
        f"Name=tag:{TAG},Values={args.name}",
        "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down",
        "--query",
        "Reservations[].Instances[]",
    )
    return out[0] if out else None


def require_instance(args: argparse.Namespace) -> dict:
    inst = find_instance(args)
    if not inst or inst["State"]["Name"] != "running":
        sys.exit(f"no running pod named {args.name!r}; start one with `up`")
    return inst


def ssh_base(args: argparse.Namespace, inst: dict) -> list[str]:
    return [
        "ssh",
        "-i",
        str(key_path(args.name)),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={STATE_DIR / 'known_hosts'}",
        "-o",
        "ServerAliveInterval=30",
        f"{SSH_USER}@{inst['PublicIpAddress']}",
    ]


def remote(args: argparse.Namespace, inst: dict, script: str, check: bool = True) -> int:
    """Run a bash script on the pod, in ~/tome, with uv on PATH."""
    env = ""
    if os.environ.get("HF_TOKEN"):
        env = f"export HF_TOKEN={shlex.quote(os.environ['HF_TOKEN'])}; "
    wrapped = (
        f"{env}export PATH=$HOME/.local/bin:$PATH; mkdir -p ~/{REMOTE_DIR} && cd ~/{REMOTE_DIR} "
        f"&& {script}"
    )
    rc = subprocess.run([*ssh_base(args, inst), "bash", "-lc", shlex.quote(wrapped)]).returncode
    if check and rc != 0:
        sys.exit(f"remote command failed ({rc})")
    return rc


def rsync(args: argparse.Namespace, inst: dict, *paths: str, upload: bool, extra=()) -> None:
    ssh = " ".join(shlex.quote(a) for a in ssh_base(args, inst)[:-1])
    host = f"{SSH_USER}@{inst['PublicIpAddress']}"
    if upload:
        cmd = ["rsync", "-az", "--relative", *extra, "-e", ssh, *paths, f"{host}:{REMOTE_DIR}/"]
    else:
        srcs = [f"{host}:{REMOTE_DIR}/./{p}" for p in paths]
        cmd = ["rsync", "-az", "--relative", *extra, "-e", ssh, *srcs, "./"]
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        sys.exit("rsync failed")


# --- subcommands -------------------------------------------------------------


def cmd_up(args: argparse.Namespace) -> None:
    if inst := find_instance(args):
        sys.exit(
            f"pod {args.name!r} already exists ({inst['InstanceId']}, "
            f"{inst['State']['Name']}); use `down` first"
        )
    reg = region(args)
    log(f"region {reg} (confirm it is your project's Region)")

    ami = args.ami or aws(
        args,
        "ec2",
        "describe-images",
        "--owners",
        "amazon",
        "--filters",
        f"Name=name,Values={AMI_NAME}",
        "Name=state,Values=available",
        "--query",
        "sort_by(Images,&CreationDate)[-1].ImageId",
    )
    if not ami:
        sys.exit(f"no AMI matching {AMI_NAME!r} in {reg}; pass --ami")
    root_dev = aws(
        args, "ec2", "describe-images", "--image-ids", ami, "--query", "Images[0].RootDeviceName"
    )
    log(f"AMI {ami}")

    vpc = aws(
        args,
        "ec2",
        "describe-vpcs",
        "--filters",
        "Name=is-default,Values=true",
        "--query",
        "Vpcs[0].VpcId",
    )
    if not vpc:
        sys.exit(f"no default VPC in {reg}; create one with `aws ec2 create-default-vpc`")

    # Default subnets in the zones that offer the instance type. GPU capacity is
    # often short in one zone and free in the next, so `up` tries each in turn.
    zones = aws(
        args,
        "ec2",
        "describe-instance-type-offerings",
        "--location-type",
        "availability-zone",
        "--filters",
        f"Name=instance-type,Values={args.instance_type}",
        "--query",
        "InstanceTypeOfferings[].Location",
    )
    subnets = aws(
        args,
        "ec2",
        "describe-subnets",
        "--filters",
        f"Name=vpc-id,Values={vpc}",
        "Name=default-for-az,Values=true",
        "--query",
        "Subnets[].[SubnetId,AvailabilityZone]",
    )
    subnets = sorted((az, sn) for sn, az in subnets or [] if az in (zones or []))
    if not subnets:
        sys.exit(f"no default subnet in a zone offering {args.instance_type} in {reg}")

    tags = f"{{Key={TAG},Value={args.name}}},{{Key=Name,Value=tome-{args.name}}}"

    # Key pair: a fresh one per pod, private key kept only under .cache/.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    kp = key_path(args.name)
    key_name = f"tome-{args.name}"
    aws(args, "ec2", "delete-key-pair", "--key-name", key_name, check=False)
    material = aws(
        args,
        "ec2",
        "create-key-pair",
        "--key-name",
        key_name,
        "--key-type",
        "ed25519",
        "--tag-specifications",
        f"ResourceType=key-pair,Tags=[{tags}]",
        "--query",
        "KeyMaterial",
    )
    kp.unlink(missing_ok=True)
    kp.write_text(material)
    kp.chmod(0o600)
    (STATE_DIR / "known_hosts").unlink(missing_ok=True)

    # Security group: SSH from this machine's public IP only.
    ip = my_ip()
    sg = aws(
        args,
        "ec2",
        "create-security-group",
        "--group-name",
        f"tome-{args.name}",
        "--description",
        "tome GPU pod: SSH from one IP",
        "--vpc-id",
        vpc,
        "--tag-specifications",
        f"ResourceType=security-group,Tags=[{tags}]",
        "--query",
        "GroupId",
    )
    aws(
        args,
        "ec2",
        "authorize-security-group-ingress",
        "--group-id",
        sg,
        "--ip-permissions",
        json.dumps(
            [
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": f"{ip}/32", "Description": "tome gpu_pod.py up"}],
                }
            ]
        ),
    )
    log(f"security group {sg}: SSH from {ip}/32 only")

    # The dead-man switch: power off after max-hours; power-off = terminate.
    minutes = int(args.max_hours * 60)
    user_data = f"#!/bin/bash\nshutdown -h +{minutes} 'tome pod time limit'\n"

    inst = None
    for az, subnet in subnets:
        inst = aws(
            args,
            "ec2",
            "run-instances",
            "--subnet-id",
            subnet,
            "--image-id",
            ami,
            "--instance-type",
            args.instance_type,
            "--key-name",
            key_name,
            "--security-group-ids",
            sg,
            "--instance-initiated-shutdown-behavior",
            "terminate",
            "--metadata-options",
            "HttpTokens=required,HttpEndpoint=enabled",
            "--block-device-mappings",
            json.dumps(
                [
                    {
                        "DeviceName": root_dev,
                        "Ebs": {
                            "VolumeSize": args.disk_gb,
                            "VolumeType": "gp3",
                            "DeleteOnTermination": True,
                            "Encrypted": True,
                        },
                    }
                ]
            ),
            "--user-data",
            user_data,
            "--tag-specifications",
            f"ResourceType=instance,Tags=[{tags}]",
            f"ResourceType=volume,Tags=[{tags}]",
            "--query",
            "Instances[0]",
            check=False,
        )
        if inst:
            log(f"{az}: launched")
            break
        if "InsufficientInstanceCapacity" not in aws.last_error:
            sys.exit(f"aws ec2 run-instances failed:\n{aws.last_error}")
        log(f"{az}: {aws.last_error.splitlines()[-1][:300]}")
    if not inst:
        cmd_down(args)  # remove the security group and key pair made above
        sys.exit(f"no {args.instance_type} capacity in any zone of {reg}; try again later")
    iid = inst["InstanceId"]
    log(f"launched {iid} ({args.instance_type}); self-terminates in {args.max_hours:g} h")
    aws(args, "ec2", "wait", "instance-running", "--instance-ids", iid)
    inst = require_instance(args)
    log(f"running at {inst['PublicIpAddress']}; waiting for SSH")
    for _ in range(60):
        probe = [
            *ssh_base(args, inst)[:1],
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            *ssh_base(args, inst)[1:],
            "true",
        ]
        if subprocess.run(probe, capture_output=True).returncode == 0:
            log("SSH ready")
            return
        time.sleep(5)
    sys.exit("SSH did not come up within 5 minutes (instance left running; run `down`)")


def cmd_setup(args: argparse.Namespace) -> None:
    inst = require_instance(args)
    log("copying code (no library/, data/ or corpus/)")
    excludes = [f"--exclude={e}" for e in RSYNC_EXCLUDES]
    rsync(args, inst, ".", upload=True, extra=excludes)
    log("installing uv, tome and vLLM")
    remote(
        args,
        inst,
        (
            "command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh; "
            "export PATH=$HOME/.local/bin:$PATH; "
            "uv sync --frozen && "
            f"(test -x ~/vllm/bin/vllm || (uv venv --python 3.12 ~/vllm && "
            f"VIRTUAL_ENV=~/vllm uv pip install vllm=={VLLM_VERSION})) && "
            "nvidia-smi --query-gpu=name,memory.total --format=csv"
        ),
    )


def cmd_vllm(args: argparse.Namespace) -> None:
    inst = require_instance(args)
    extra = " ".join(shlex.quote(a) for a in args.vllm_args)
    log(f"starting vLLM: {args.model}")
    remote(
        args,
        inst,
        (
            # A pidfile, not pkill -f: this shell's own command line contains "vllm serve".
            "if [ -f ~/vllm.pid ]; then kill $(cat ~/vllm.pid) 2>/dev/null; sleep 5; fi; "
            f"nohup ~/vllm/bin/vllm serve {shlex.quote(args.model)} --host 127.0.0.1 "
            f"--port {VLLM_PORT} --max-model-len {args.max_model_len} {extra} "
            "< /dev/null > ~/vllm.log 2>&1 & echo $! > ~/vllm.pid; "
            # Model download + load can take a while for 70B; vllm.log shows progress.
            f"for i in $(seq 1 {args.wait_minutes * 12}); do "
            f"  curl -sf localhost:{VLLM_PORT}/v1/models >/dev/null "
            "&& echo 'vLLM ready' && exit 0; "
            "  kill -0 $(cat ~/vllm.pid) 2>/dev/null || { tail -40 ~/vllm.log; exit 1; }; "
            "  sleep 5; "
            "done; tail -40 ~/vllm.log; exit 1"
        ),
    )


def cmd_push(args: argparse.Namespace) -> None:
    for p in args.paths:
        if not (ROOT / p).exists():
            sys.exit(f"{p}: not found (paths are relative to the repo root)")
    rsync(args, require_instance(args), *args.paths, upload=True)


def cmd_pull(args: argparse.Namespace) -> None:
    rsync(args, require_instance(args), *args.paths, upload=False)
    for p in args.paths:
        log(f"pulled {p}")


def cmd_exec(args: argparse.Namespace) -> None:
    if not args.command:
        sys.exit("nothing to run; put the command after --")
    cmd = " ".join(shlex.quote(a) for a in args.command)
    rc = remote(args, require_instance(args), cmd, check=False)
    if rc:
        sys.exit(rc)


def cmd_ssh(args: argparse.Namespace) -> None:
    inst = require_instance(args)
    base = ssh_base(args, inst)
    os.execvp("ssh", [*base[:-1], *args.ssh_args, base[-1]])


def cmd_status(args: argparse.Namespace) -> None:
    inst = find_instance(args)
    if not inst:
        print(f"no pod named {args.name!r} in {region(args)}")
        return
    launched = inst["LaunchTime"]
    print(
        f"{inst['InstanceId']}  {inst['InstanceType']}  {inst['State']['Name']}  "
        f"{inst.get('PublicIpAddress', '-')}  launched {launched}"
    )


def cmd_down(args: argparse.Namespace) -> None:
    inst = find_instance(args)
    if inst:
        iid = inst["InstanceId"]
        log(f"terminating {iid}")
        aws(args, "ec2", "terminate-instances", "--instance-ids", iid)
        aws(args, "ec2", "wait", "instance-terminated", "--instance-ids", iid)
    sgs = aws(
        args,
        "ec2",
        "describe-security-groups",
        "--filters",
        f"Name=tag:{TAG},Values={args.name}",
        "--query",
        "SecurityGroups[].GroupId",
    )
    for sg in sgs or []:
        aws(args, "ec2", "delete-security-group", "--group-id", sg)
        log(f"deleted security group {sg}")
    aws(args, "ec2", "delete-key-pair", "--key-name", f"tome-{args.name}", check=False)
    key_path(args.name).unlink(missing_ok=True)
    # The root volume has DeleteOnTermination; check nothing tagged was left behind.
    vols = aws(
        args,
        "ec2",
        "describe-volumes",
        "--filters",
        f"Name=tag:{TAG},Values={args.name}",
        "--query",
        "Volumes[].VolumeId",
    )
    if vols:
        log(f"WARNING: volumes still exist: {vols} (deleting)")
        for v in vols:
            aws(args, "ec2", "delete-volume", "--volume-id", v, check=False)
    log("pod destroyed")


def cmd_run(args: argparse.Namespace) -> None:
    cmd_up(args)
    try:
        cmd_setup(args)
        cmd_vllm(args)
        if args.push:
            args.paths = args.push
            cmd_push(args)
        if args.command:
            cmd_exec(args)
        if args.pull:
            args.paths = args.pull
            cmd_pull(args)
    finally:
        if args.keep:
            log("--keep: pod left running (it still self-terminates at --max-hours)")
        else:
            cmd_down(args)


# --- CLI ---------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--name", default="default", help="pod name (tag), to run several at once")
    p.add_argument("--region", help="AWS region (default: the AWS CLI's)")
    p.add_argument("--profile", help="AWS CLI profile")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_up_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--instance-type", default=INSTANCE_TYPE)
        sp.add_argument("--ami", help="AMI id (default: latest Deep Learning Base AMI)")
        sp.add_argument("--disk-gb", type=int, default=ROOT_VOLUME_GB)
        sp.add_argument(
            "--max-hours",
            type=float,
            default=3.0,
            help="hard time limit; the instance terminates itself (default 3)",
        )

    def add_vllm_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--model", required=True, help="Hugging Face model id")
        sp.add_argument("--max-model-len", type=int, default=16384)
        sp.add_argument("--wait-minutes", type=int, default=30)
        sp.add_argument(
            "--vllm-arg",
            dest="vllm_args",
            action="append",
            default=[],
            help="extra `vllm serve` argument (repeatable), e.g. --vllm-arg=--quantization=awq",
        )

    add_up_opts(sub.add_parser("up", help="launch the instance and wait for SSH"))
    sub.add_parser("setup", help="copy the code; install uv, tome and vLLM")
    add_vllm_opts(sub.add_parser("vllm", help="(re)start vLLM on the pod and wait until ready"))
    sp = sub.add_parser("push", help="copy local files (repo-relative) to the pod")
    sp.add_argument("paths", nargs="+")
    sp = sub.add_parser("pull", help="copy pod files (repo-relative) back here")
    sp.add_argument("paths", nargs="+")
    sp = sub.add_parser("exec", help="run a command in ~/tome on the pod")
    sp.add_argument("command", nargs=argparse.REMAINDER)
    sp = sub.add_parser("ssh", help="interactive shell (extra ssh args after --)")
    sp.add_argument("ssh_args", nargs=argparse.REMAINDER)
    sub.add_parser("status", help="show the pod, if any")
    sub.add_parser("down", help="terminate the instance; delete its security group and key pair")
    sp = sub.add_parser("run", help="up, setup, vllm, push, exec, pull, down")
    add_up_opts(sp)
    add_vllm_opts(sp)
    sp.add_argument("--push", action="append", default=[], help="file to upload (repeatable)")
    sp.add_argument("--pull", action="append", default=[], help="file to download (repeatable)")
    sp.add_argument("--keep", action="store_true", help="don't run `down` at the end")
    sp.add_argument("command", nargs=argparse.REMAINDER)

    args = p.parse_args()
    for attr in ("command", "ssh_args"):
        if getattr(args, attr, None) and getattr(args, attr)[0] == "--":
            setattr(args, attr, getattr(args, attr)[1:])
    globals()[f"cmd_{args.cmd}"](args)


if __name__ == "__main__":
    main()

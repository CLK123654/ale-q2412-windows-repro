from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOLUTION = ROOT / "implementation/chart_solution"
EXPECTED_INPUTS = {
    "README.md",
    "change_request.md",
    "phase_plan.csv",
    "rotation_contract.json",
    "secret_registry.csv",
    "starter/callback-keyring/Chart.yaml",
    "starter/callback-keyring/templates/deployment.yaml",
    "starter/callback-keyring/templates/service.yaml",
    "starter/callback-keyring/values-activate.yaml",
    "starter/callback-keyring/values-preload.yaml",
    "starter/callback-keyring/values-retire.yaml",
    "starter/callback-keyring/values-steady.yaml",
    "starter/callback-keyring/values.yaml",
}
REGISTRY_FIELDS = ["key_id", "secret_name", "secret_key", "status", "available_from", "retire_after"]
PHASE_FIELDS = ["phase", "sequence", "rotation_revision", "active_key", "accepted_keys"]


def rows(path: Path, fields: list[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fields:
            raise ValueError(f"{path.name}表头不匹配")
        return list(reader)


def write_csv(path: Path, fields: list[str], values: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(values)


def helm(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=60)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--helm", required=True)
    args = parser.parse_args()
    input_root = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    try:
        actual = {path.relative_to(input_root).as_posix() for path in input_root.rglob("*") if path.is_file()}
        if actual != EXPECTED_INPUTS:
            raise ValueError("输入文件集合不匹配")
        contract = json.loads((input_root / "rotation_contract.json").read_text(encoding="utf-8"))
        registry_rows = rows(input_root / "secret_registry.csv", REGISTRY_FIELDS)
        phase_rows = rows(input_root / "phase_plan.csv", PHASE_FIELDS)
        registry = {row["key_id"]: row for row in registry_rows}
        if len(registry) != len(registry_rows) or not registry:
            raise ValueError("Secret登记主键无效")
        phases = [row["phase"] for row in phase_rows]
        if phases != contract["phases_in_order"] or len(set(phases)) != len(phases):
            raise ValueError("轮换阶段顺序无效")
        if [int(row["sequence"]) for row in phase_rows] != list(range(1, len(phase_rows) + 1)):
            raise ValueError("轮换序号不连续")
        for row in phase_rows:
            accepted = row["accepted_keys"].split("|")
            if row["active_key"] not in accepted or not accepted or len(set(accepted)) != len(accepted):
                raise ValueError(f"{row['phase']}阶段active与accepted关系无效")
            if any(key not in registry for key in accepted):
                raise ValueError(f"{row['phase']}阶段引用未登记Secret")

        chart = output / "chart"
        rendered = output / "rendered"
        reports = output / "reports"
        shutil.copytree(SOLUTION, chart)
        starter_chart = input_root / "starter/callback-keyring"
        starter_meta = yaml.safe_load((starter_chart / "Chart.yaml").read_text(encoding="utf-8"))
        starter_values = yaml.safe_load((starter_chart / "values.yaml").read_text(encoding="utf-8"))
        if starter_meta.get("name") != "callback-keyring":
            raise ValueError("starter Chart身份无效")
        values_path = chart / "values.yaml"
        chart_values = yaml.safe_load(values_path.read_text(encoding="utf-8"))
        chart_values["image"] = starter_values["image"]
        chart_values["service"] = starter_values["service"]
        chart_values["secretRefs"] = {
            key_id: {"name": row["secret_name"], "key": row["secret_key"]}
            for key_id, row in registry.items()
        }
        values_path.write_text(yaml.safe_dump(chart_values, sort_keys=False), encoding="utf-8")
        rendered.mkdir(parents=True)
        reports.mkdir()

        lint = helm([args.helm, "lint", str(chart), "--strict"])
        if lint.returncode != 0:
            raise RuntimeError(lint.stdout + lint.stderr)

        ledger: list[dict[str, object]] = []
        reference_review: list[dict[str, object]] = []
        required_objects = set(contract["required_objects"])
        for phase in phase_rows:
            phase_name = phase["phase"]
            values = chart / f"values-{phase_name}.yaml"
            process = helm([
                args.helm, "template", contract["release_name"], str(chart),
                "--namespace", contract["namespace"], "--values", str(values),
            ])
            if process.returncode != 0:
                raise RuntimeError(process.stderr + process.stdout)
            documents = [doc for doc in yaml.safe_load_all(process.stdout) if isinstance(doc, dict)]
            if any(doc.get("kind") == "Secret" for doc in documents):
                raise ValueError(f"{phase_name}阶段Chart创建了Secret")
            objects = {
                f"{doc.get('kind')}/{doc.get('metadata', {}).get('name')}"
                for doc in documents
            }
            if not required_objects.issubset(objects):
                raise ValueError(f"{phase_name}阶段缺少合同对象")
            deployment = next(doc for doc in documents if doc.get("kind") == "Deployment")
            configmap = next(doc for doc in documents if doc.get("kind") == "ConfigMap")
            accepted = phase["accepted_keys"].split("|")
            volume = next(item for item in deployment["spec"]["template"]["spec"]["volumes"] if item["name"] == "keyring")
            sources = volume["projected"]["sources"]
            actual_names = [item["secret"]["name"] for item in sources]
            actual_keys = [item["secret"]["items"][0]["key"] for item in sources]
            actual_paths = [item["secret"]["items"][0]["path"] for item in sources]
            expected_names = [registry[key]["secret_name"] for key in accepted]
            expected_keys = [registry[key]["secret_key"] for key in accepted]
            expected_paths = [f"{key}.key" for key in accepted]
            if actual_names != expected_names or actual_keys != expected_keys or actual_paths != expected_paths:
                raise ValueError(f"{phase_name}阶段Secret投影不匹配")
            if configmap["data"] != {
                "phase": phase_name,
                "rotationRevision": phase["rotation_revision"],
                "activeKey": phase["active_key"],
                "acceptedKeys": ",".join(accepted),
            }:
                raise ValueError(f"{phase_name}阶段ConfigMap不匹配")
            annotations = deployment["spec"]["template"]["metadata"]["annotations"]
            if annotations.get("keyring.example.com/rotation-revision") != phase["rotation_revision"]:
                raise ValueError(f"{phase_name}阶段修订号不匹配")
            (rendered / f"{phase_name}.yaml").write_text(process.stdout, encoding="utf-8")
            ledger.append({
                "phase": phase_name,
                "sequence": phase["sequence"],
                "rotation_revision": phase["rotation_revision"],
                "active_key": phase["active_key"],
                "accepted_keys": phase["accepted_keys"],
                "secret_names": "|".join(actual_names),
                "mount_paths": "|".join(actual_paths),
                "manifest_path": f"rendered/{phase_name}.yaml",
            })
            for index, key_id in enumerate(accepted):
                reference_review.append({
                    "phase": phase_name,
                    "projection_order": index + 1,
                    "key_id": key_id,
                    "secret_name": actual_names[index],
                    "secret_key": actual_keys[index],
                    "mount_path": actual_paths[index],
                    "registry_status": registry[key_id]["status"],
                })

        write_csv(reports / "rotation_ledger.csv", [
            "phase", "sequence", "rotation_revision", "active_key", "accepted_keys",
            "secret_names", "mount_paths", "manifest_path",
        ], ledger)
        write_csv(reports / "secret_reference_review.csv", [
            "phase", "projection_order", "key_id", "secret_name", "secret_key",
            "mount_path", "registry_status",
        ], reference_review)
        (output / "change_note.md").write_text(
            "# 回调验签Secret轮换\n\n"
            "周四维护窗先使用preload阶段同时挂载新旧两代Secret，再由activate阶段启用新钥。旧签名观察期结束后才进入retire阶段。\n\n"
            "Chart只引用平台密钥组登记的Secret，不创建Secret对象，也不读取密钥正文。发布评审人核对rendered与reports，维护窗值班负责现场应用、验签观察和回滚。\n\n"
            "activate阶段出现异常时，使用preload阶段values和清单回滚。Secret创建、权限与密钥正文仍由平台密钥组处理。\n",
            encoding="utf-8",
        )
        (output / "README.md").write_text(
            "# 使用说明\n\nchart保存完整HelmChart，rendered保存各轮换阶段清单，reports连接阶段计划与Secret登记，change_note.md记录维护窗和回滚分工。\n",
            encoding="utf-8",
        )
    except Exception:
        if output.exists():
            shutil.rmtree(output)
        raise


if __name__ == "__main__":
    main()

"""Regenerate evolve_charts/score_catalog.py from Evolve's score calculation source.

Usage (from the repository root):

    python tools/sync_scores.py [path/to/evolve]

`.evolve` files hold the measurements, not the scores: Evolve calculates the scores whenever it reads a
run. This copies what that calculation needs from the Rust source: the calibrated multiplier of every
score per benchmark and platform (`crates/evolve-highscore-api/src/score.rs`), the score names, and which
workload category each GPU score times (`crates/evolve-datakit-scores/src/lib.rs`).
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVOLVE = REPO_ROOT.parent / "evolve"
SCORE_RS = "crates/evolve-highscore-api/src/score.rs"
DATAKIT_SCORES_RS = "crates/evolve-datakit-scores/src/lib.rs"
OUTPUT = REPO_ROOT / "evolve_charts/score_catalog.py"

COMMENT = re.compile(r"//[^\n]*")
VARIANT_ARM = re.compile(r"((?:BenchmarkVariant::\w+\s*\|?\s*)+)=>")
SCORE_ARM = re.compile(r"((?:Self::\w+\s*\|?\s*)+)=>\s*(return None|[0-9_.]+)")
SOME_ARM = re.compile(r"((?:BenchmarkVariant::\w+\s*\|?\s*)+)=>\s*Some\(([0-9_.]+)\)")
F32_CONST = re.compile(r"const (\w+): f32 = ([0-9_.]+);")


def _function(source: str, name: str) -> str:
    start = source.index(f"fn {name}(")
    following = re.compile(r"\n\s*(?:pub(?:\([\w:]+\))? )?(?:const )?fn ").search(source, start + 1)
    return COMMENT.sub("", source[start : following.start() if following else len(source)])


def _number(text: str) -> float:
    return float(text.replace("_", ""))


def _variants(text: str) -> list[str]:
    return re.findall(r"BenchmarkVariant::(\w+)", text)


def _multipliers(source: str, function: str) -> dict[str, dict[str, float]]:
    """Benchmark variant -> score -> multiplier; a score the variant doesn't have is absent."""
    body = _function(source, function)
    arms = list(VARIANT_ARM.finditer(body))
    table: dict[str, dict[str, float]] = {}
    for arm, following in zip(arms, [*arms[1:], None]):
        text = body[arm.end() : following.start() if following else len(body)]
        scores = {
            score: _number(value)
            for names, value in SCORE_ARM.findall(text)
            if value != "return None"
            for score in re.findall(r"Self::(\w+)", names)
        }
        for variant in _variants(arm.group(1)):
            table[variant] = scores
    if not table:
        raise SystemExit(f"Found no multipliers in `{function}`; has {SCORE_RS} changed shape?")
    return table


def parse(score_rs: str, datakit_scores_rs: str) -> dict:
    platforms = {
        "Desktop": _multipliers(score_rs, "desktop_score_multipliers"),
        "Phone": _multipliers(score_rs, "mobile_score_multipliers"),
    }
    handheld = _function(score_rs, "handheld_score_multipliers")
    if "self.desktop_score_multipliers(variant)" not in handheld:
        raise SystemExit("Handheld multipliers are no longer the desktop ones; teach this tool to read them.")
    platforms["Handheld"] = platforms["Desktop"]

    enum = score_rs[score_rs.index("pub enum Score {") :]
    order = re.findall(r"^\s*(\w+),$", enum[: enum.index("}")], re.MULTILINE)
    name_body = _function(score_rs, "name")
    names = dict(re.findall(r'Self::(\w+) => "([^"]+)"', name_body))

    version = re.search(r"DRIVER_EXCLUDES_PRESENT: EvolveVersion = EvolveVersion::new\((\d+), (\d+)\)", score_rs)
    phone_driver = {
        variant: _number(value)
        for variants, value in SOME_ARM.findall(_function(score_rs, "mobile_driver_multiplier_with_present"))
        for variant in _variants(variants)
    }
    energy = re.search(r"\(([0-9_.]+) \* \(-m as f32 \* avg\)\.exp\(\)\)", score_rs)
    gpu_scores = re.findall(r"\(\s*WorkloadCategory::(\w+),\s*Score::(\w+),?\s*\)", datakit_scores_rs)
    if not (version and energy and gpu_scores and phone_driver):
        raise SystemExit("Couldn't find every score constant; has the Rust source changed shape?")

    return {
        "SCORE_ORDER": order,
        "SCORE_NAMES": {score: names[score] for score in order},
        "GPU_SCORES": dict(gpu_scores),
        "MULTIPLIERS": platforms,
        "DRIVER_EXCLUDES_PRESENT": (int(version.group(1)), int(version.group(2))),
        "PHONE_DRIVER_WITH_PRESENT": phone_driver,
        "ENERGY_SCALE": _number(energy.group(1)),
        "IMAGE_QUALITY": {name: _number(value) for name, value in F32_CONST.findall(score_rs)},
    }


COMMENTS = {
    "SCORE_ORDER": "Score variants, in the order Evolve lists them",
    "SCORE_NAMES": "Score variant -> the name Evolve shows",
    "GPU_SCORES": "WorkloadCategory variant -> the Score of its GPU time",
    "MULTIPLIERS": "Platform -> BenchmarkVariant -> Score -> multiplier; a score a benchmark doesn't have is absent",
    "DRIVER_EXCLUDES_PRESENT": "Phone Driver scores of runs before this Evolve version use PHONE_DRIVER_WITH_PRESENT",
    "PHONE_DRIVER_WITH_PRESENT": "BenchmarkVariant -> phone Driver multiplier from before DRIVER_EXCLUDES_PRESENT",
    "ENERGY_SCALE": "Energy score = ENERGY_SCALE * exp(-multiplier * average power in W)",
    "IMAGE_QUALITY": "FLIP and SSIM pooling and normalization constants",
}


def main() -> None:
    evolve = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVOLVE
    catalog = parse(
        (evolve / SCORE_RS).read_text(encoding="utf-8"), (evolve / DATAKIT_SCORES_RS).read_text(encoding="utf-8")
    )
    lines = [
        "# Generated by tools/sync_scores.py from evolve/crates/evolve-highscore-api/src/score.rs",
        "# and evolve/crates/evolve-datakit-scores/src/lib.rs. Do not edit by hand.",
        "",
    ]
    for name, value in catalog.items():
        lines += [f"# {COMMENTS[name]}", f"{name} = {value!r}", ""]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Wrote {sum(len(v) for v in catalog['MULTIPLIERS'].values())} benchmark multiplier sets to {OUTPUT.name}")


if __name__ == "__main__":
    main()

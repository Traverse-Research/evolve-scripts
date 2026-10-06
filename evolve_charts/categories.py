"""Evolve's workload categories, and which GPU scope (render pass) belongs to which.

Evolve times **passes**, single blocks of GPU work. A **workload category** (`WorkloadCategory`) is GPU work
that logically belongs together, and what Evolve scores: all ray tracing work is the Raytracing workload,
whose score is the Ray Tracing score.

Which pass belongs to which workload category comes from `scope_catalog.py`, generated from Evolve's Rust
source by `tools/sync_categories.py`. Passes Evolve leaves uncategorized are left out of the tool.
"""

from .scope_catalog import UNCATEGORIZED_PASSES, WORKLOAD_NAMES, WORKLOADS

WORKLOAD_DESCRIPTIONS = {
    "Raytracing": "All ray tracing work: tracing rays for shadows, reflections, lighting and path tracing.",
    "Acceleration Structure Builds": "Building and updating the structures (BVHs) that make ray tracing fast.",
    "Rasterization": "Drawing triangles to the screen, the classic way of rendering.",
    "Compute": "General-purpose GPU programs: denoising, lighting, post-processing, animation, ...",
    "Workgraphs": "GPU work that schedules more GPU work by itself (DirectX 12 work graphs).",
    "NRC": "The neural radiance cache: a small neural network that learns how light bounces.",
    "Upscaling": "Upscaling a lower-resolution image to the output resolution (FSR, XeSS, ...).",
}
# Evolve's order, also used in charts.
WORKLOAD_ORDER = list(WORKLOAD_DESCRIPTIONS)


def workloads(scope: str) -> list[str]:
    """The workload categories the pass is part of, in Evolve's order; empty if Evolve leaves it uncategorized.

    Almost every pass is part of exactly one; Evolve lists a handful in two.
    """
    names = {WORKLOAD_NAMES.get(variant) for variant in WORKLOADS.get(scope, [])}
    return [name for name in WORKLOAD_ORDER if name in names]


def is_utility(scope: str) -> bool:
    """Support work like copies, clears and the user interface, which isn't worth listing as a pass.

    These are the passes Evolve's pass bucketing leaves uncategorized. Some of those still do the work of a
    workload category of their own (upscalers, the neural radiance cache) and are kept.
    """
    return scope in UNCATEGORIZED_PASSES and set(workloads(scope)) <= {"Compute"}

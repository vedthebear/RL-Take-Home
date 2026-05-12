"""Pydantic models — the wire schema both halves of the bridge agree on.

This file is the *contract* between the MCP-server side (which validates with
these classes) and the Blender-addon side (which emits matching plain dicts).
Editing a field here without mirroring the change in
``blender_addon/handlers/*.py`` will produce ``internal_error`` responses for
that tool.

Layout: shared validators and aliases first, then ``Failure`` and the wire
envelopes, then one section per tool ordered to match the 12-tool surface.

Design contract:

- Every tool input is a single ``BaseModel`` validated by FastMCP before the
  handler runs.
- Every tool returns a discriminated union ``<Tool>Ok | Failure`` on a
  ``status`` field. Discriminator depth is 1 — variants of variants confuse
  both pydantic and the FastMCP-generated JSON schema.
- All units are explicit in the field name: ``rotation_euler_deg`` carries
  degrees; energy is in watts (or W/m^2 for sun lights); colors are linear
  RGB in [0, 1].
- Names are validated against Blender's restrictions in one place; the
  ``ObjectName`` alias is reused everywhere.

This module imports nothing Blender-specific so it can be unit-tested without
``bpy`` available.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Constants & shared aliases
# ---------------------------------------------------------------------------

NAME_MAX_LEN: Final[int] = 63
NAME_INVALID_CHARS: Final[frozenset[str]] = frozenset('/\\:*?"<>|')
COORD_BOUND: Final[float] = 10_000.0
ROTATION_BOUND_DEG: Final[float] = 360.0 * 10  # allow generous winding
SCALE_BOUND: Final[float] = 10_000.0

Vec3 = tuple[float, float, float]
RGB = tuple[float, float, float]  # linear, [0, 1] per channel


def _validate_object_name(v: str) -> str:
    if not v or not v.strip():
        raise ValueError("name cannot be empty or whitespace-only")
    if len(v) > NAME_MAX_LEN:
        raise ValueError(f"name exceeds Blender's {NAME_MAX_LEN}-char limit")
    bad = sorted(NAME_INVALID_CHARS & set(v))
    if bad:
        raise ValueError(f"name contains invalid characters: {''.join(bad)}")
    return v


def _validate_location(v: Vec3) -> Vec3:
    if any(abs(c) > COORD_BOUND for c in v):
        raise ValueError(f"location must be within +/-{COORD_BOUND} on every axis")
    return v


def _validate_rotation_deg(v: Vec3) -> Vec3:
    if any(abs(c) > ROTATION_BOUND_DEG for c in v):
        raise ValueError(
            f"rotation_euler_deg must be within +/-{ROTATION_BOUND_DEG} per axis"
        )
    return v


def _validate_scale(v: Vec3) -> Vec3:
    if any(c <= 0 for c in v):
        raise ValueError("scale components must be strictly positive")
    if any(c > SCALE_BOUND for c in v):
        raise ValueError(f"scale must be within (0, {SCALE_BOUND}] per axis")
    return v


def _validate_rgb(v: RGB) -> RGB:
    if any(c < 0.0 or c > 1.0 for c in v):
        raise ValueError("color channels must be in [0, 1] (linear)")
    return v


ObjectName = Annotated[str, AfterValidator(_validate_object_name)]
Location = Annotated[Vec3, AfterValidator(_validate_location)]
RotationDeg = Annotated[Vec3, AfterValidator(_validate_rotation_deg)]
Scale = Annotated[Vec3, AfterValidator(_validate_scale)]
LinearRGB = Annotated[RGB, AfterValidator(_validate_rgb)]


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------

ErrorCode = Literal[
    "object_not_found",
    "name_collision",
    "invalid_state",
    "blender_op_failed",
    "timeout",
    "connection_lost",
    "validation_error",
    "unknown_command",
    "internal_error",
]


class Failure(BaseModel):
    """Structured failure result for any tool."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["error"] = "error"
    code: ErrorCode
    message: str = Field(min_length=1, max_length=1_000)
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Wire envelopes
# ---------------------------------------------------------------------------


class CommandEnvelope(BaseModel):
    """MCP-server -> addon: a tool invocation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


class ResponseEnvelope(BaseModel):
    """Addon -> MCP-server: result of a command.

    ``payload`` is the tool's structured result (either a success-type dict or
    a Failure dict). Keeping it loosely typed at this layer lets the MCP-side
    tool function re-validate against its specific output model.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Shared brief views (used inside Ok responses)
# ---------------------------------------------------------------------------


class SceneObjectBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    location: Vec3
    hidden: bool


class RenderSettingsBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str
    resolution: tuple[int, int]
    samples: int
    output_filepath: str


class MaterialSlotBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_index: int
    material_name: str | None
    base_color: RGB | None = None
    metallic: float | None = None
    roughness: float | None = None


class ModifierBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str


class MeshStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vertices: int
    edges: int
    faces: int


# ---------------------------------------------------------------------------
# 1. get_scene_summary
# ---------------------------------------------------------------------------

SceneFilterType = Literal["all", "mesh", "camera", "light", "empty", "curve", "other"]


class GetSceneSummaryInput(BaseModel):
    """Filterable, paginated snapshot of the current scene."""

    model_config = ConfigDict(extra="forbid")

    filter_type: SceneFilterType = "all"
    name_contains: str | None = Field(default=None, max_length=63)
    limit: int = Field(default=100, ge=1, le=10_000)
    offset: int = Field(default=0, ge=0)
    include_render_settings: bool = True


class GetSceneSummaryOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    total_objects: int
    returned_count: int
    objects: list[SceneObjectBrief]
    counts_by_type: dict[str, int]
    active_camera: str | None
    render: RenderSettingsBrief | None


GetSceneSummaryResult = Annotated[
    Union[GetSceneSummaryOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 2. get_object
# ---------------------------------------------------------------------------


class GetObjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ObjectName
    include_mesh_stats: bool = True


class GetObjectOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    name: str
    type: str
    location: Vec3
    rotation_euler_deg: Vec3
    scale: Vec3
    bbox_world_min: Vec3 | None
    bbox_world_max: Vec3 | None
    material_slots: list[MaterialSlotBrief]
    modifiers: list[ModifierBrief]
    mesh_stats: MeshStats | None


GetObjectResult = Annotated[
    Union[GetObjectOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 3. render_image
# ---------------------------------------------------------------------------

# Engine strings accepted on the wire. Blender 5.0 removed the legacy EEVEE
# and renamed "BLENDER_EEVEE_NEXT" back to "BLENDER_EEVEE". The addon accepts
# either form and canonicalizes to whatever the running Blender expects.
RenderEngine = Literal["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES"]

# Cap inline image payload at 4 MiB; larger renders still write to disk but
# return only the filepath. Keeps Claude's context manageable.
INLINE_IMAGE_MAX_BYTES: Final[int] = 4 * 1024 * 1024


class RenderImageInput(BaseModel):
    """Render the current scene from the active camera."""

    model_config = ConfigDict(extra="forbid")

    filepath: str | None = Field(
        default=None,
        max_length=1024,
        description="Output path. If None, a temp file is used.",
    )
    engine: RenderEngine = "BLENDER_EEVEE"
    resolution: tuple[int, int] = (1280, 720)
    samples: int = Field(default=64, ge=1, le=4096)
    return_image: bool = True

    @field_validator("resolution")
    @classmethod
    def _check_resolution(cls, v: tuple[int, int]) -> tuple[int, int]:
        w, h = v
        if w < 16 or h < 16 or w > 8192 or h > 8192:
            raise ValueError("resolution width/height must be within [16, 8192]")
        return v


class RenderImageOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    filepath: str
    width: int
    height: int
    engine: str
    image_base64: str | None = None
    image_skipped_reason: str | None = None


RenderImageResult = Annotated[
    Union[RenderImageOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 4. add_primitive (discriminated union)
# ---------------------------------------------------------------------------


class _PrimBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CubeParams(_PrimBase):
    kind: Literal["cube"] = "cube"
    size: float = Field(default=2.0, gt=0.0, le=1000.0)


class SphereParams(_PrimBase):
    kind: Literal["sphere"] = "sphere"
    radius: float = Field(default=1.0, gt=0.0, le=1000.0)
    segments: int = Field(default=32, ge=3, le=256)
    rings: int = Field(default=16, ge=3, le=256)


class CylinderParams(_PrimBase):
    kind: Literal["cylinder"] = "cylinder"
    radius: float = Field(default=1.0, gt=0.0, le=1000.0)
    depth: float = Field(default=2.0, gt=0.0, le=1000.0)
    vertices: int = Field(default=32, ge=3, le=512)


class ConeParams(_PrimBase):
    kind: Literal["cone"] = "cone"
    radius_bottom: float = Field(default=1.0, ge=0.0, le=1000.0)
    radius_top: float = Field(default=0.0, ge=0.0, le=1000.0)
    depth: float = Field(default=2.0, gt=0.0, le=1000.0)
    vertices: int = Field(default=32, ge=3, le=512)

    @model_validator(mode="after")
    def _radii_not_both_zero(self) -> ConeParams:
        if self.radius_bottom == 0.0 and self.radius_top == 0.0:
            raise ValueError("at least one of radius_bottom or radius_top must be > 0")
        return self


class PlaneParams(_PrimBase):
    kind: Literal["plane"] = "plane"
    size: float = Field(default=2.0, gt=0.0, le=1000.0)


PrimitiveKind = Literal["cube", "sphere", "cylinder", "cone", "plane"]

PrimitiveParams = Annotated[
    Union[CubeParams, SphereParams, CylinderParams, ConeParams, PlaneParams],
    Field(discriminator="kind"),
]


class AddPrimitiveInput(BaseModel):
    """Create a mesh primitive at a given transform."""

    model_config = ConfigDict(extra="forbid")

    params: PrimitiveParams
    name: ObjectName
    location: Location = (0.0, 0.0, 0.0)
    rotation_euler_deg: RotationDeg = (0.0, 0.0, 0.0)
    scale: Scale = (1.0, 1.0, 1.0)


class AddPrimitiveOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    name: str  # actual assigned name (may differ from request if Blender deduped)
    kind: PrimitiveKind
    location: Vec3


AddPrimitiveResult = Annotated[
    Union[AddPrimitiveOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 5. add_modifier (discriminated union)
# ---------------------------------------------------------------------------


class _ModBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubsurfMod(_ModBase):
    kind: Literal["subdivision_surface"] = "subdivision_surface"
    levels: int = Field(default=2, ge=0, le=6)
    render_levels: int = Field(default=2, ge=0, le=6)
    subdivision_type: Literal["CATMULL_CLARK", "SIMPLE"] = "CATMULL_CLARK"


class BevelMod(_ModBase):
    kind: Literal["bevel"] = "bevel"
    width: float = Field(default=0.1, gt=0.0, le=100.0)
    segments: int = Field(default=2, ge=1, le=32)
    profile: float = Field(default=0.5, ge=0.0, le=1.0)
    limit_method: Literal["NONE", "ANGLE", "WEIGHT"] = "ANGLE"
    angle_limit_deg: float = Field(default=30.0, ge=0.0, le=180.0)


class ArrayMod(_ModBase):
    kind: Literal["array"] = "array"
    count: int = Field(default=3, ge=1, le=1000)
    relative_offset: Vec3 = (1.0, 0.0, 0.0)


class BooleanMod(_ModBase):
    kind: Literal["boolean"] = "boolean"
    operation: Literal["UNION", "DIFFERENCE", "INTERSECT"] = "DIFFERENCE"
    target_object: ObjectName
    solver: Literal["FAST", "EXACT"] = "EXACT"


class SolidifyMod(_ModBase):
    kind: Literal["solidify"] = "solidify"
    thickness: float = Field(default=0.05, gt=0.0, le=100.0)
    offset: float = Field(default=-1.0, ge=-1.0, le=1.0)


ModifierKind = Literal[
    "subdivision_surface", "bevel", "array", "boolean", "solidify"
]

ModifierParams = Annotated[
    Union[SubsurfMod, BevelMod, ArrayMod, BooleanMod, SolidifyMod],
    Field(discriminator="kind"),
]


class AddModifierInput(BaseModel):
    """Attach a modifier to an object. Optionally apply (bake) immediately."""

    model_config = ConfigDict(extra="forbid")

    object_name: ObjectName
    params: ModifierParams
    modifier_name: str | None = Field(default=None, min_length=1, max_length=63)
    apply_immediately: bool = False


class AddModifierOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    object_name: str
    modifier_name: str  # actual assigned name
    kind: ModifierKind
    applied: bool


AddModifierResult = Annotated[
    Union[AddModifierOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 6. transform_object
# ---------------------------------------------------------------------------


class TransformObjectInput(BaseModel):
    """Set or delta-update an object's transform.

    All three transform fields are optional, but at least one must be given.
    In ``set`` mode the given fields replace the current values; in ``delta``
    mode they are added componentwise (and scale is multiplied componentwise).
    """

    model_config = ConfigDict(extra="forbid")

    name: ObjectName
    mode: Literal["set", "delta"] = "set"
    location: Vec3 | None = None
    rotation_euler_deg: Vec3 | None = None
    scale: Vec3 | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> TransformObjectInput:
        if (
            self.location is None
            and self.rotation_euler_deg is None
            and self.scale is None
        ):
            raise ValueError(
                "must provide at least one of: location, rotation_euler_deg, scale"
            )
        return self

    @field_validator("location")
    @classmethod
    def _loc_bounds(cls, v: Vec3 | None) -> Vec3 | None:
        return None if v is None else _validate_location(v)

    @field_validator("rotation_euler_deg")
    @classmethod
    def _rot_bounds(cls, v: Vec3 | None) -> Vec3 | None:
        return None if v is None else _validate_rotation_deg(v)

    @field_validator("scale")
    @classmethod
    def _scale_bounds(cls, v: Vec3 | None) -> Vec3 | None:
        if v is None:
            return None
        # In delta mode, scale acts multiplicatively; positive is still required.
        if any(c <= 0 for c in v):
            raise ValueError("scale components must be strictly positive")
        if any(c > SCALE_BOUND for c in v):
            raise ValueError(f"scale must be within (0, {SCALE_BOUND}] per axis")
        return v


class TransformObjectOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    name: str
    location: Vec3
    rotation_euler_deg: Vec3
    scale: Vec3


TransformObjectResult = Annotated[
    Union[TransformObjectOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 7. duplicate_object
# ---------------------------------------------------------------------------


class DuplicateObjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: ObjectName
    new_name: ObjectName | None = None
    location_offset: Location = (0.0, 0.0, 0.0)
    linked: bool = False  # share mesh data with source (cheaper, but data-coupled)


class DuplicateObjectOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    source_name: str
    new_name: str
    location: Vec3
    linked: bool


DuplicateObjectResult = Annotated[
    Union[DuplicateObjectOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 8. delete_object
# ---------------------------------------------------------------------------


class DeleteObjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ObjectName


class DeleteObjectOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    name: str


DeleteObjectResult = Annotated[
    Union[DeleteObjectOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 9. set_material
# ---------------------------------------------------------------------------


class SetMaterialInput(BaseModel):
    """Create (or reuse) a Principled BSDF material and assign it to an object.

    Colors are linear RGB in [0, 1]. The material is named ``material_name``;
    if a material with that name already exists, it is updated in place rather
    than duplicated.
    """

    model_config = ConfigDict(extra="forbid")

    object_name: ObjectName
    material_name: ObjectName
    base_color: LinearRGB = (0.8, 0.8, 0.8)
    metallic: float = Field(default=0.0, ge=0.0, le=1.0)
    roughness: float = Field(default=0.5, ge=0.0, le=1.0)
    alpha: float = Field(default=1.0, ge=0.0, le=1.0)
    emission_color: LinearRGB | None = None
    emission_strength: float = Field(default=0.0, ge=0.0, le=10_000.0)
    slot_index: int | None = Field(default=None, ge=0, le=63)


class SetMaterialOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    object_name: str
    material_name: str
    slot_index: int
    created_new_material: bool


SetMaterialResult = Annotated[
    Union[SetMaterialOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 10. add_light (discriminated union)
# ---------------------------------------------------------------------------


class _LightBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PointLightParams(_LightBase):
    kind: Literal["point"] = "point"
    energy: float = Field(default=1000.0, ge=0.0, le=1_000_000.0)
    color: LinearRGB = (1.0, 1.0, 1.0)
    shadow_soft_size: float = Field(default=0.25, ge=0.0, le=100.0)


class SunLightParams(_LightBase):
    kind: Literal["sun"] = "sun"
    energy: float = Field(default=3.0, ge=0.0, le=1_000.0)
    color: LinearRGB = (1.0, 1.0, 1.0)
    angle_deg: float = Field(default=0.5, ge=0.0, le=180.0)


class SpotLightParams(_LightBase):
    kind: Literal["spot"] = "spot"
    energy: float = Field(default=1000.0, ge=0.0, le=1_000_000.0)
    color: LinearRGB = (1.0, 1.0, 1.0)
    spot_size_deg: float = Field(default=45.0, ge=1.0, le=180.0)
    spot_blend: float = Field(default=0.15, ge=0.0, le=1.0)
    shadow_soft_size: float = Field(default=0.25, ge=0.0, le=100.0)


class AreaLightParams(_LightBase):
    kind: Literal["area"] = "area"
    energy: float = Field(default=100.0, ge=0.0, le=1_000_000.0)
    color: LinearRGB = (1.0, 1.0, 1.0)
    shape: Literal["SQUARE", "RECTANGLE", "DISK", "ELLIPSE"] = "SQUARE"
    size: float = Field(default=1.0, gt=0.0, le=1000.0)
    size_y: float = Field(default=1.0, gt=0.0, le=1000.0)


LightKind = Literal["point", "sun", "spot", "area"]

LightParams = Annotated[
    Union[PointLightParams, SunLightParams, SpotLightParams, AreaLightParams],
    Field(discriminator="kind"),
]


class AddLightInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: LightParams
    name: ObjectName
    location: Location = (0.0, 0.0, 0.0)
    rotation_euler_deg: RotationDeg = (0.0, 0.0, 0.0)


class AddLightOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    name: str
    kind: LightKind
    location: Vec3


AddLightResult = Annotated[
    Union[AddLightOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 11. add_camera
# ---------------------------------------------------------------------------


class AddCameraInput(BaseModel):
    """Add a perspective camera. Optionally aims at ``target_object`` via a
    Track-To constraint and/or sets itself as the scene's active camera.
    """

    model_config = ConfigDict(extra="forbid")

    name: ObjectName
    location: Location = (7.0, -7.0, 5.0)
    rotation_euler_deg: RotationDeg = (60.0, 0.0, 45.0)
    focal_length_mm: float = Field(default=50.0, ge=1.0, le=300.0)
    target_object: ObjectName | None = None
    set_active: bool = True
    dof_focus_distance: float | None = Field(default=None, ge=0.0, le=COORD_BOUND)
    dof_aperture_fstop: float | None = Field(default=None, ge=0.1, le=128.0)

    @model_validator(mode="after")
    def _dof_pair(self) -> AddCameraInput:
        a = self.dof_focus_distance is not None
        b = self.dof_aperture_fstop is not None
        if a != b:
            raise ValueError(
                "dof_focus_distance and dof_aperture_fstop must be set together"
            )
        return self


class AddCameraOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    name: str
    location: Vec3
    is_active: bool
    tracking: str | None  # name of the target_object, if a Track-To was added


AddCameraResult = Annotated[
    Union[AddCameraOk, Failure], Field(discriminator="status")
]


# ---------------------------------------------------------------------------
# 12. clear_scene
# ---------------------------------------------------------------------------


class ClearSceneInput(BaseModel):
    """Remove all objects from the scene, with an optional allowlist."""

    model_config = ConfigDict(extra="forbid")

    keep: list[ObjectName] = Field(default_factory=list, max_length=1000)
    also_remove_orphans: bool = True


class ClearSceneOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    removed_objects: list[str]
    kept_objects: list[str]
    orphans_removed: int


ClearSceneResult = Annotated[
    Union[ClearSceneOk, Failure], Field(discriminator="status")
]

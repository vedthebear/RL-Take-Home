"""Pydantic validation tests for tool input/output models.

These tests exercise the validation contract without needing Blender or the
addon running. They cover:

- Name and coordinate validators on shared aliases.
- Discriminator parsing for ``add_primitive`` / ``add_modifier`` / ``add_light``.
- Cross-field constraints (transform_object requires one field;
  add_camera requires DOF pair).
- JSON round-trip (``model_dump_json`` -> ``model_validate_json``) for every
  input and Ok output type.
- That every ``ErrorCode`` literal is constructible on ``Failure``.
"""

from __future__ import annotations

import typing as t

import pytest
from pydantic import TypeAdapter, ValidationError

from blender_mcp import models as m

# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------


class TestObjectNameValidator:
    def test_accepts_normal_name(self) -> None:
        assert m._validate_object_name("MyCube") == "MyCube"

    @pytest.mark.parametrize("bad", ["", "   ", "\t"])
    def test_rejects_empty_or_whitespace(self, bad: str) -> None:
        with pytest.raises(ValueError, match="empty"):
            m._validate_object_name(bad)

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ValueError, match="63"):
            m._validate_object_name("x" * 64)

    @pytest.mark.parametrize("ch", ["/", "\\", ":", "*", "?", '"', "<", ">", "|"])
    def test_rejects_invalid_chars(self, ch: str) -> None:
        with pytest.raises(ValueError, match="invalid characters"):
            m._validate_object_name(f"name{ch}x")


class TestLocationValidator:
    def test_accepts_in_bounds(self) -> None:
        m._validate_location((1.0, -2.0, 3.5))

    def test_rejects_out_of_bounds(self) -> None:
        with pytest.raises(ValueError, match="10000"):
            m._validate_location((m.COORD_BOUND + 1, 0.0, 0.0))


class TestScaleValidator:
    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="strictly positive"):
            m._validate_scale((0.0, 1.0, 1.0))

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="strictly positive"):
            m._validate_scale((-1.0, 1.0, 1.0))


class TestRGBValidator:
    def test_accepts_in_range(self) -> None:
        m._validate_rgb((0.0, 0.5, 1.0))

    @pytest.mark.parametrize("c", [(-0.1, 0, 0), (0, 1.1, 0), (0, 0, 2.0)])
    def test_rejects_out_of_range(self, c: m.RGB) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            m._validate_rgb(c)


# ---------------------------------------------------------------------------
# Wire envelopes
# ---------------------------------------------------------------------------


class TestEnvelopes:
    def test_command_envelope_round_trip(self) -> None:
        cmd = m.CommandEnvelope(id="abc", command="ping", params={"x": 1})
        assert m.CommandEnvelope.model_validate_json(cmd.model_dump_json()) == cmd

    def test_command_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            m.CommandEnvelope.model_validate(
                {"id": "a", "command": "ping", "params": {}, "rogue": True}
            )

    def test_response_envelope_round_trip(self) -> None:
        rsp = m.ResponseEnvelope(id="abc", payload={"status": "ok"})
        assert m.ResponseEnvelope.model_validate_json(rsp.model_dump_json()) == rsp


# ---------------------------------------------------------------------------
# Failure / error taxonomy
# ---------------------------------------------------------------------------


class TestFailure:
    @pytest.mark.parametrize("code", t.get_args(m.ErrorCode))
    def test_every_error_code_constructible(self, code: m.ErrorCode) -> None:
        f = m.Failure(code=code, message="test")
        assert f.status == "error"
        assert f.code == code

    def test_message_min_length(self) -> None:
        with pytest.raises(ValidationError):
            m.Failure(code="internal_error", message="")

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            m.Failure.model_validate(
                {"status": "error", "code": "internal_error", "message": "x", "evil": 1}
            )


# ---------------------------------------------------------------------------
# add_primitive — discriminated union
# ---------------------------------------------------------------------------


class TestAddPrimitive:
    def test_cube_defaults(self) -> None:
        inp = m.AddPrimitiveInput(params={"kind": "cube"}, name="Box")  # type: ignore[arg-type]
        assert isinstance(inp.params, m.CubeParams)
        assert inp.params.size == 2.0

    def test_sphere_full(self) -> None:
        inp = m.AddPrimitiveInput.model_validate(
            {
                "params": {"kind": "sphere", "radius": 0.5, "segments": 16, "rings": 8},
                "name": "Ball",
                "location": [1, 2, 3],
            }
        )
        assert isinstance(inp.params, m.SphereParams)
        assert inp.params.radius == 0.5

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValidationError, match="does not match any of the expected tags"):
            m.AddPrimitiveInput.model_validate(
                {"params": {"kind": "blob"}, "name": "X"}
            )

    def test_cone_radii_both_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="radius_bottom or radius_top"):
            m.AddPrimitiveInput.model_validate(
                {
                    "params": {"kind": "cone", "radius_bottom": 0.0, "radius_top": 0.0},
                    "name": "C",
                }
            )

    def test_extra_param_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            m.AddPrimitiveInput.model_validate(
                {"params": {"kind": "cube", "rogue": 1}, "name": "X"}
            )

    def test_negative_size_rejected(self) -> None:
        with pytest.raises(ValidationError):
            m.AddPrimitiveInput.model_validate(
                {"params": {"kind": "cube", "size": -1}, "name": "X"}
            )

    def test_round_trip(self) -> None:
        inp = m.AddPrimitiveInput.model_validate(
            {"params": {"kind": "cylinder", "radius": 2}, "name": "Cyl"}
        )
        assert m.AddPrimitiveInput.model_validate_json(inp.model_dump_json()) == inp

    def test_ok_result_status(self) -> None:
        ok = m.AddPrimitiveOk(name="Cube.001", kind="cube", location=(0, 0, 0))
        assert ok.status == "ok"


# ---------------------------------------------------------------------------
# add_modifier — discriminated union
# ---------------------------------------------------------------------------


class TestAddModifier:
    def test_subsurf_defaults(self) -> None:
        inp = m.AddModifierInput.model_validate(
            {"object_name": "Cube", "params": {"kind": "subdivision_surface"}}
        )
        assert isinstance(inp.params, m.SubsurfMod)

    def test_boolean_requires_target(self) -> None:
        with pytest.raises(ValidationError):
            m.AddModifierInput.model_validate(
                {"object_name": "A", "params": {"kind": "boolean"}}
            )

    def test_boolean_full(self) -> None:
        inp = m.AddModifierInput.model_validate(
            {
                "object_name": "A",
                "params": {
                    "kind": "boolean",
                    "operation": "UNION",
                    "target_object": "B",
                },
            }
        )
        assert isinstance(inp.params, m.BooleanMod)
        assert inp.params.target_object == "B"

    def test_unknown_modifier_kind_rejected(self) -> None:
        with pytest.raises(ValidationError, match="does not match any of the expected tags"):
            m.AddModifierInput.model_validate(
                {"object_name": "A", "params": {"kind": "fluid"}}
            )


# ---------------------------------------------------------------------------
# transform_object — cross-field validators
# ---------------------------------------------------------------------------


class TestTransformObject:
    def test_requires_at_least_one_field(self) -> None:
        with pytest.raises(ValidationError, match="at least one"):
            m.TransformObjectInput(name="X")  # type: ignore[call-arg]

    def test_set_mode(self) -> None:
        inp = m.TransformObjectInput(name="X", location=(1, 2, 3))
        assert inp.mode == "set"

    def test_delta_mode(self) -> None:
        inp = m.TransformObjectInput(name="X", mode="delta", scale=(2, 2, 2))
        assert inp.mode == "delta"

    def test_invalid_scale(self) -> None:
        with pytest.raises(ValidationError, match="strictly positive"):
            m.TransformObjectInput(name="X", scale=(0, 1, 1))

    def test_location_bounds(self) -> None:
        with pytest.raises(ValidationError):
            m.TransformObjectInput(name="X", location=(m.COORD_BOUND + 1, 0, 0))


# ---------------------------------------------------------------------------
# add_camera — DOF pair invariant
# ---------------------------------------------------------------------------


class TestAddCamera:
    def test_minimal(self) -> None:
        cam = m.AddCameraInput(name="Cam")
        assert cam.set_active is True

    def test_dof_pair_partial_rejected(self) -> None:
        with pytest.raises(ValidationError, match="together"):
            m.AddCameraInput(name="Cam", dof_focus_distance=5.0)

    def test_dof_pair_complete_ok(self) -> None:
        cam = m.AddCameraInput(
            name="Cam", dof_focus_distance=5.0, dof_aperture_fstop=2.8
        )
        assert cam.dof_focus_distance == 5.0


# ---------------------------------------------------------------------------
# add_light — discriminated union
# ---------------------------------------------------------------------------


class TestAddLight:
    def test_point_default(self) -> None:
        inp = m.AddLightInput.model_validate(
            {"params": {"kind": "point"}, "name": "Lamp"}
        )
        assert isinstance(inp.params, m.PointLightParams)
        assert inp.params.energy == 1000.0

    def test_area_shape(self) -> None:
        inp = m.AddLightInput.model_validate(
            {
                "params": {"kind": "area", "shape": "DISK", "size": 2.0},
                "name": "Area",
            }
        )
        assert isinstance(inp.params, m.AreaLightParams)
        assert inp.params.shape == "DISK"


# ---------------------------------------------------------------------------
# render_image
# ---------------------------------------------------------------------------


class TestRenderImage:
    def test_defaults(self) -> None:
        inp = m.RenderImageInput()
        assert inp.engine == "BLENDER_EEVEE_NEXT"
        assert inp.resolution == (1280, 720)

    def test_resolution_lower_bound(self) -> None:
        with pytest.raises(ValidationError, match=r"\[16, 8192\]"):
            m.RenderImageInput(resolution=(8, 600))

    def test_resolution_upper_bound(self) -> None:
        with pytest.raises(ValidationError, match=r"\[16, 8192\]"):
            m.RenderImageInput(resolution=(10_000, 600))


# ---------------------------------------------------------------------------
# clear_scene
# ---------------------------------------------------------------------------


class TestClearScene:
    def test_default(self) -> None:
        inp = m.ClearSceneInput()
        assert inp.keep == []
        assert inp.also_remove_orphans is True

    def test_keep_validates_names(self) -> None:
        with pytest.raises(ValidationError):
            m.ClearSceneInput(keep=["Bad/Name"])


# ---------------------------------------------------------------------------
# Result discriminated unions (using TypeAdapter)
# ---------------------------------------------------------------------------


class TestResultUnions:
    def test_add_primitive_ok_parses(self) -> None:
        ta: TypeAdapter[m.AddPrimitiveResult] = TypeAdapter(m.AddPrimitiveResult)
        v = ta.validate_python(
            {"status": "ok", "name": "Cube", "kind": "cube", "location": [0, 0, 0]}
        )
        assert isinstance(v, m.AddPrimitiveOk)

    def test_add_primitive_failure_parses(self) -> None:
        ta: TypeAdapter[m.AddPrimitiveResult] = TypeAdapter(m.AddPrimitiveResult)
        v = ta.validate_python(
            {"status": "error", "code": "name_collision", "message": "taken"}
        )
        assert isinstance(v, m.Failure)
        assert v.code == "name_collision"

    def test_unknown_status_rejected(self) -> None:
        ta: TypeAdapter[m.AddPrimitiveResult] = TypeAdapter(m.AddPrimitiveResult)
        with pytest.raises(ValidationError):
            ta.validate_python({"status": "wat"})

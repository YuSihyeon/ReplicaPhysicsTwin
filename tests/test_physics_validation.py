from __future__ import annotations

import unittest

from replica_physics_twin.physics_validation import (
    create_simulation_from_xml,
    run_drop_scenario,
    run_impulse_scenario,
    validate_drop_result,
)


TEST_XML = """<mujoco model="phase2_fixture">
  <option gravity="0 0 -9.81" timestep="0.002" integrator="Euler"/>
  <default>
    <geom friction="0.8 0.1 0.1" solref="0.005 1" solimp="0.9 0.95 0.001"/>
  </default>
  <worldbody>
    <geom name="floor" type="plane" pos="0 0 0" size="2 2 0.1"/>
    <body name="test_box" pos="0 0 0.35">
      <freejoint/>
      <geom name="test_box_geom" type="box" size="0.05 0.05 0.05" mass="0.1"/>
    </body>
  </worldbody>
  <keyframe>
    <key name="initial" qpos="0 0 0.35 1 0 0 0" qvel="0 0 0 0 0 0"/>
  </keyframe>
</mujoco>"""


class PhysicsValidationTests(unittest.TestCase):
    def test_drop_validation_passes_and_records_contact(self) -> None:
        model, data = create_simulation_from_xml(TEST_XML)

        result = run_drop_scenario(model, data, max_steps=2000)
        validation = validate_drop_result(result)

        self.assertTrue(validation["passed"], validation)
        self.assertTrue(validation["gravity_drop"])
        self.assertTrue(validation["floor_not_passed"])
        self.assertTrue(validation["stable_after_contact"])
        self.assertGreaterEqual(validation["contact_count"], 1)

    def test_impulse_changes_velocity_in_requested_direction(self) -> None:
        model, data = create_simulation_from_xml(TEST_XML)
        impulse = [0.1, 0.0, 0.0]

        before = [float(value) for value in data.qvel[:3]]
        result = run_impulse_scenario(model, data, "test_box", impulse)

        self.assertEqual(before, [0.0, 0.0, 0.0])
        self.assertGreater(result["velocity_after"][0], 0.0)
        self.assertEqual(result["velocity_after"][1], 0.0)
        self.assertAlmostEqual(result["velocity_delta_mps"][2], -9.81 * 0.002, places=12)
        self.assertTrue(result["direction_ok"], result)


if __name__ == "__main__":
    unittest.main()

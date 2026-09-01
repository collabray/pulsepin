from app.models.hospital import CapabilityCode
from app.services.facility_matching import CONDITION_CAPABILITY_MAP, capabilities_required_for


def test_every_condition_maps_to_valid_capability_codes():
    valid_codes = {c.value for c in CapabilityCode}
    for condition, caps in CONDITION_CAPABILITY_MAP.items():
        for c in caps:
            assert c.value in valid_codes, f"{condition} maps to invalid capability {c}"


def test_heart_attack_requires_cath_lab():
    caps = capabilities_required_for("Heart attack")
    assert CapabilityCode.CATH_LAB in caps


def test_unknown_condition_falls_back_to_emergency_room():
    caps = capabilities_required_for("Some condition not in the map")
    assert caps == [CapabilityCode.EMERGENCY_ROOM]


def test_every_triage_label_has_a_capability_mapping_entry():
    """
    Every disease the triage model can output should have an explicit
    (even if empty-list) entry in CONDITION_CAPABILITY_MAP, so routing
    never silently falls back to a generic default for a condition the
    model actually predicts.
    """
    import json
    from pathlib import Path

    labels_path = Path(__file__).parent.parent / "ml" / "artifacts" / "triage_labels.json"
    with open(labels_path) as f:
        labels = json.load(f)

    missing = [l for l in labels if l not in CONDITION_CAPABILITY_MAP]
    assert not missing, f"Triage labels missing from capability map: {missing}"

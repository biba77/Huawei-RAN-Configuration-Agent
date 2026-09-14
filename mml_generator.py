from xml_engine import ChangeRecord

# Logical parameter
MML_TEMPLATES = {
    "tilt": ("MOD", "ANTENNARETCFG", "ELECTRICALTILT"),
    "power": ("MOD", "CELL", "TXPOWER"),
    "pci": ("MOD", "CELL", "PHYCELLID"),
    "bandwidth": ("MOD", "CELL", "DLBANDWIDTH"),
    "ul_bandwidth": ("MOD", "CELL", "ULBANDWIDTH"),
}


def generate_mml(change: ChangeRecord) -> str:
    if change.parameter not in MML_TEMPLATES:
        raise ValueError(f"No MML template for parameter '{change.parameter}'")

    verb, obj, mml_param = MML_TEMPLATES[change.parameter]
    return f"{verb} {obj}: LOCALCELLID={change.local_cell_id}, {mml_param}={change.new_value};"


if __name__ == "__main__":
    demo = ChangeRecord(local_cell_id=1, parameter="tilt", xml_tag="ElectricalTilt",
                         old_value="4", new_value="6")
    print(generate_mml(demo))

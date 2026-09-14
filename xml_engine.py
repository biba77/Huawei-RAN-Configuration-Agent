import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional


@dataclass
class ChangeRecord:
    local_cell_id: int
    parameter: str          # logical name: "tilt", "power", "pci", "bandwidth"
    xml_tag: str             # actual XML tag changed, e.g. "ElectricalTilt"
    old_value: str
    new_value: str


class UnknownCellError(Exception):
    pass


class UnknownParameterError(Exception):
    pass


# Maps the logical parameter name (what an engineer would say in English)
# to how it's actually stored in the XML.
PARAM_MAP = {
    "tilt": {"element": "Antenna", "tag": "ElectricalTilt", "linked_by": "LinkedCellId"},
    "power": {"element": "Cell", "tag": "TxPower", "linked_by": None},
    "pci": {"element": "Cell", "tag": "PhyCellId", "linked_by": None},
    "bandwidth": {"element": "Cell", "tag": "DlBandWidth", "linked_by": None},
    "ul_bandwidth": {"element": "Cell", "tag": "UlBandWidth", "linked_by": None},
}


class RANConfig:
    def __init__(self, xml_path: str):
        self.xml_path = xml_path
        self.tree = ET.parse(xml_path)
        self.root = self.tree.getroot()

    # ---------- lookups ----------

    def _find_cell(self, local_cell_id: int) -> ET.Element:
        for cell in self.root.iter("Cell"):
            id_el = cell.find("LocalCellId")
            if id_el is not None and int(id_el.text) == local_cell_id:
                return cell
        raise UnknownCellError(f"No Cell found with LocalCellId={local_cell_id}")

    def _find_antenna_for_cell(self, local_cell_id: int) -> ET.Element:
        for ant in self.root.iter("Antenna"):
            link_el = ant.find("LinkedCellId")
            if link_el is not None and int(link_el.text) == local_cell_id:
                return ant
        raise UnknownCellError(f"No Antenna linked to LocalCellId={local_cell_id}")

    def list_cells(self):
        """Returns a quick summary of every cell, useful for the chatbot to
        validate a request or answer 'what cells exist' style questions."""
        cells = []
        for cell in self.root.iter("Cell"):
            cells.append({
                "local_cell_id": int(cell.find("LocalCellId").text),
                "cell_name": cell.find("CellName").text,
                "pci": int(cell.find("PhyCellId").text),
                "tx_power": int(cell.find("TxPower").text),
                "dl_bandwidth": cell.find("DlBandWidth").text,
            })
        return cells

    def get_parameter(self, local_cell_id: int, parameter: str) -> str:
        parameter = parameter.lower()
        if parameter not in PARAM_MAP:
            raise UnknownParameterError(f"Unknown parameter '{parameter}'")
        spec = PARAM_MAP[parameter]
        if spec["element"] == "Antenna":
            el = self._find_antenna_for_cell(local_cell_id)
        else:
            el = self._find_cell(local_cell_id)
        return el.find(spec["tag"]).text

    # ---------- updates ----------

    def set_parameter(self, local_cell_id: int, parameter: str, new_value) -> ChangeRecord:
        """Updates the in-memory XML tree. Call save() to persist to disk."""
        parameter = parameter.lower()
        if parameter not in PARAM_MAP:
            raise UnknownParameterError(f"Unknown parameter '{parameter}'")
        spec = PARAM_MAP[parameter]

        if spec["element"] == "Antenna":
            el = self._find_antenna_for_cell(local_cell_id)
        else:
            el = self._find_cell(local_cell_id)

        target = el.find(spec["tag"])
        old_value = target.text
        target.text = str(new_value)

        # If tilt changed, TotalTilt (Mechanical + Electrical) should stay
        # consistent -- this is exactly the kind of derived-field logic a
        # naive find/replace would miss.
        if parameter == "tilt":
            mech = el.find("MechanicalTilt")
            total = el.find("TotalTilt")
            if mech is not None and total is not None:
                total.text = str(int(mech.text) + int(new_value))

        return ChangeRecord(
            local_cell_id=local_cell_id,
            parameter=parameter,
            xml_tag=spec["tag"],
            old_value=old_value,
            new_value=str(new_value),
        )

    def save(self, output_path: Optional[str] = None):
        """Writes the (possibly modified) tree back to disk. Defaults to
        overwriting the original file unless a new path is given."""
        path = output_path or self.xml_path
        self.tree.write(path, encoding="UTF-8", xml_declaration=True)
        return path

    def to_pretty_string(self) -> str:
        """Serializes the current in-memory tree to indented XML text.
        Used to diff before/after state without touching disk -- lets the
        caller show a preview and only save() once the engineer confirms."""
        import copy
        tree_copy = copy.deepcopy(self.tree)
        ET.indent(tree_copy, space="  ")
        return ET.tostring(tree_copy.getroot(), encoding="unicode")


if __name__ == "__main__":
    # Quick smoke test against the real file
    cfg = RANConfig("huawei_enodeb_SITE001_clean.xml")
    print("Cells found:", cfg.list_cells())

    change = cfg.set_parameter(1, "tilt", 4)
    print("Change made:", change)

    out = cfg.save("huawei_enodeb_SITE001_updated.xml")
    print("Saved to:", out)

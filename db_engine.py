import sqlite3
from xml_engine import RANConfig, ChangeRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS enodeb (
    enodeb_id INTEGER PRIMARY KEY,
    enodeb_name TEXT,
    mcc TEXT,
    mnc TEXT,
    tracking_area_code TEXT,
    freq_band INTEGER
);

CREATE TABLE IF NOT EXISTS cells (
    local_cell_id INTEGER PRIMARY KEY,
    cell_name TEXT,
    cell_id INTEGER,
    phy_cell_id INTEGER,
    tx_power INTEGER,
    dl_bandwidth TEXT,
    ul_bandwidth TEXT,
    freq_band INTEGER,
    azimuth INTEGER,
    active_state TEXT
);

CREATE TABLE IF NOT EXISTS antennas (
    antenna_id TEXT PRIMARY KEY,
    linked_cell_id INTEGER,
    electrical_tilt INTEGER,
    mechanical_tilt INTEGER,
    total_tilt INTEGER,
    azimuth INTEGER,
    FOREIGN KEY (linked_cell_id) REFERENCES cells (local_cell_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT,
    request_text TEXT,
    local_cell_id INTEGER,
    parameter TEXT,
    old_value TEXT,
    new_value TEXT,
    mml_command TEXT
);
"""

# Maps our logical parameter name -> (table, column) so sync_change_to_db
# can update the DB with the exact same mapping xml_engine.py used to
# update the XML. Keeping this table-driven (rather than an if/elif chain)
PARAM_TO_DB_COLUMN = {
    "tilt": ("antennas", "electrical_tilt", "linked_cell_id"),
    "power": ("cells", "tx_power", "local_cell_id"),
    "pci": ("cells", "phy_cell_id", "local_cell_id"),
    "bandwidth": ("cells", "dl_bandwidth", "local_cell_id"),
    "ul_bandwidth": ("cells", "ul_bandwidth", "local_cell_id"),
}


def build_db_from_xml(xml_path: str, db_path: str):
    """Full sync: (re)creates every table from the current XML state.
    Safe to call repeatedly -- drops and rebuilds each table so the DB
    never drifts from a stale partial state."""
    config = RANConfig(xml_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
        DROP TABLE IF EXISTS enodeb;
        DROP TABLE IF EXISTS cells;
        DROP TABLE IF EXISTS antennas;
    """)
    cur.executescript(SCHEMA)

    # eNodeB (single row)
    enb = config.root.find("eNodeB")
    cur.execute(
        "INSERT INTO enodeb VALUES (?,?,?,?,?,?)",
        (
            int(enb.find("eNodeBId").text),
            enb.find("eNodeBName").text,
            enb.find("MCC").text,
            enb.find("MNC").text,
            enb.find("TrackingAreaCode").text,
            int(enb.find("FreqBand").text),
        ),
    )

    # Cells
    for cell in config.root.iter("Cell"):
        cur.execute(
            "INSERT INTO cells VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                int(cell.find("LocalCellId").text),
                cell.find("CellName").text,
                int(cell.find("CellId").text),
                int(cell.find("PhyCellId").text),
                int(cell.find("TxPower").text),
                cell.find("DlBandWidth").text,
                cell.find("UlBandWidth").text,
                int(cell.find("FreqBand").text),
                int(cell.find("Azimuth").text),
                cell.find("CellActiveState").text,
            ),
        )

    # Antennas
    for ant in config.root.iter("Antenna"):
        cur.execute(
            "INSERT INTO antennas VALUES (?,?,?,?,?,?)",
            (
                ant.find("AntennaId").text,
                int(ant.find("LinkedCellId").text),
                int(ant.find("ElectricalTilt").text),
                int(ant.find("MechanicalTilt").text),
                int(ant.find("TotalTilt").text),
                int(ant.find("Azimuth").text),
            ),
        )

    conn.commit()
    conn.close()


def sync_change_to_db(db_path: str, change: ChangeRecord):
    """Incremental sync: updates the single row/column affected by one
    confirmed change. Also recomputes total_tilt for tilt changes, mirroring
    the same derived-field logic xml_engine.py applies to the XML, so the
    DB and XML never disagree on TotalTilt."""
    table, column, key_column = PARAM_TO_DB_COLUMN[change.parameter]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        f"UPDATE {table} SET {column} = ? WHERE {key_column} = ?",
        (change.new_value, change.local_cell_id),
    )

    if change.parameter == "tilt":
        cur.execute(
            "UPDATE antennas SET total_tilt = mechanical_tilt + ? WHERE linked_cell_id = ?",
            (int(change.new_value), change.local_cell_id),
        )

    conn.commit()
    conn.close()


def log_change_to_db(db_path: str, change: ChangeRecord, mml: str, request_text: str, timestamp: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audit_log (timestamp_utc, request_text, local_cell_id, "
        "parameter, old_value, new_value, mml_command) VALUES (?,?,?,?,?,?,?)",
        (timestamp, request_text, change.local_cell_id, change.parameter,
         change.old_value, change.new_value, mml),
    )
    conn.commit()
    conn.close()


def query(db_path: str, sql: str):
    """Small convenience helper for ad-hoc checks / demo purposes."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


if __name__ == "__main__":
    build_db_from_xml("huawei_enodeb_SITE001_clean.xml", "ran_config.db")
    print("Cells table:")
    for row in query("ran_config.db", "SELECT * FROM cells"):
        print(" ", row)
    print("Antennas table:")
    for row in query("ran_config.db", "SELECT * FROM antennas"):
        print(" ", row)

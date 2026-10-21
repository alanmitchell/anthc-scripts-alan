"""Scripts to assign Alert Recipient Groups to alerts associated with certain
buildings.

This is a command line utility. It reads a file name named "group-assignments.tsv",
which provides the assignment of Alert Recipient Groups to buildings. An Example of
file is below. The file is a tab-separted file, i.e. fields in each row are separated
by tabs.  Sample group-assignments.tsv:

NSHC	NSHC-RMW-1	Elim
NSHC	NSHC-RMW-1	Golovin
NSHC	NSHC-RMW-1	Koyuk
NSHC	NSHC-RMW-1	St. Michael
NSHC	NSHC-RMW-1	Shaktoolik
NSHC	NSHC-RMW-1	Stebbins
NSHC	NSHC-RMW-1	Unalakleet
NSHC	NSHC-RMW-1	White Mountain

The first column is the Organization, and it is not used by this script.
The second column is the Title of an Alert Recipient Group. The third column is a
Building name (interpreted as "Community" in the ANTHC BMON system.)  All sensor alerts
associated with the Building specified on a row will be assigned to the Alert Recipient
Group specified on that row. In addition, the any individual Alert Recipients assignned to
the Alert that are already part of that Alert Recipient Group will be removed.

Run this script by executing the following from the command line while in this
project directory.

    uv run assign-recip-groups.py

"""

import csv
import os
import sqlite3
import sys

import settings

db_path = os.path.expanduser(settings.BMON_SQLITE_PATH)
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT title, id FROM bmsapp_alertrecipientgroup")
recip_group_id_by_title = {title.strip(): id_ for title, id_ in cur.fetchall()}

cur.execute("SELECT title, id FROM bmsapp_building")
building_id_by_title = {title.strip(): id_ for title, id_ in cur.fetchall()}

with open("group-assignments.tsv", newline="") as f:
    reader = csv.reader(f, delimiter="\t")
    rows = [
        [field.strip() for field in row]
        for row in reader
        if row and any(row)
    ]

# Validate all rows up front and abort if any Alert Recipient Group or
# Building title cannot be found, so a partial run doesn't leave the
# database in a half-updated state.
invalid_group_titles = sorted({row[1] for row in rows if row[1] not in recip_group_id_by_title})
invalid_building_titles = sorted({row[2] for row in rows if row[2] not in building_id_by_title})

if invalid_group_titles or invalid_building_titles:
    if invalid_group_titles:
        print("Invalid Alert Recipient Group titles:")
        for title in invalid_group_titles:
            print(f"  {title}")
    if invalid_building_titles:
        print("Invalid Building titles:")
        for title in invalid_building_titles:
            print(f"  {title}")
    conn.close()
    sys.exit(1)

for row in rows:
    _org, group_title, building_title = row[:3]

    group_id = recip_group_id_by_title[group_title]
    building_id = building_id_by_title[building_title]

    # Sensors associated with this building.
    cur.execute(
        "SELECT sensor_id FROM bmsapp_bldgtosensor WHERE building_id = ?",
        (building_id,),
    )
    sensor_ids = [r[0] for r in cur.fetchall()]
    if not sensor_ids:
        print(f"{building_title}: 0 Alerts processed")
        continue

    # Sensor alerts (Alert Conditions) that use those sensors.
    placeholders = ",".join("?" * len(sensor_ids))
    cur.execute(
        f"SELECT id FROM bmsapp_alertcondition WHERE sensor_id IN ({placeholders})",
        sensor_ids,
    )
    alert_condition_ids = [r[0] for r in cur.fetchall()]

    # Individual recipients who already belong to the Alert Recipient Group.
    cur.execute(
        "SELECT alertrecipient_id FROM bmsapp_alertrecipientgroup_recipients "
        "WHERE alertrecipientgroup_id = ?",
        (group_id,),
    )
    group_member_ids = [r[0] for r in cur.fetchall()]

    for alert_condition_id in alert_condition_ids:
        # Assign the Alert Recipient Group to the alert, if not already assigned.
        cur.execute(
            "SELECT 1 FROM bmsapp_alertcondition_recipient_groups "
            "WHERE alertcondition_id = ? AND alertrecipientgroup_id = ?",
            (alert_condition_id, group_id),
        )
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO bmsapp_alertcondition_recipient_groups "
                "(alertcondition_id, alertrecipientgroup_id) VALUES (?, ?)",
                (alert_condition_id, group_id),
            )

        # Remove individual recipients from the alert if they are already
        # covered by the Alert Recipient Group just assigned.
        if group_member_ids:
            member_placeholders = ",".join("?" * len(group_member_ids))
            cur.execute(
                "DELETE FROM bmsapp_alertcondition_recipients "
                f"WHERE alertcondition_id = ? AND alertrecipient_id IN ({member_placeholders})",
                (alert_condition_id, *group_member_ids),
            )

    print(f"{building_title}: {len(alert_condition_ids)} Alerts processed")

conn.commit()
conn.close()

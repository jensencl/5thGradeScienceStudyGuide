# /// script
# requires-python = ">=3.11"
# dependencies = [
#    "streamlit",
#    "pandas",
#    "matplotlib",
#    "psycopg2-binary",
#    "sqlalchemy",
# ]
# ///

from datetime import datetime
import io
import math
import random
import re
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from sqlalchemy import text

# Global label color for universal high-contrast legibility across dark/light themes
LABEL_COLOR = "#ef4444"

# ==============================================================================
# 1. DATABASE SETUP & PERSISTENCE (NEON POSTGRESQL)
# ==============================================================================
def get_db():
    return st.connection("neon", type="sql")


def init_db():
    schema_statements = [
        """
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS topic_mastery (
            student_id INTEGER,
            topic TEXT,
            mastery REAL DEFAULT 0.0,
            PRIMARY KEY (student_id, topic)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS attempt_logs (
            id SERIAL PRIMARY KEY,
            student_id INTEGER,
            topic TEXT,
            template_id TEXT,
            is_correct INTEGER,
            selected_answer TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    try:
        conn = get_db()
        with conn.session as s:
            for stmt in schema_statements:
                s.execute(text(stmt))
            s.commit()
    except Exception:
        st.cache_resource.clear()
        conn = get_db()
        with conn.session as s:
            for stmt in schema_statements:
                s.execute(text(stmt))
            s.commit()


def list_students():
    conn = get_db()
    with conn.session as s:
        result = s.execute(text("SELECT id, name FROM students ORDER BY name ASC"))
        rows = result.fetchall()
        return [{"id": row[0], "name": row[1]} for row in rows]


def get_or_create_student(name: str):
    clean_name = name.strip().capitalize()
    if not clean_name:
        return None
    conn = get_db()
    with conn.session as s:
        result = s.execute(
            text("SELECT id, name FROM students WHERE name = :name"),
            {"name": clean_name},
        )
        row = result.fetchone()
        if row:
            return {"id": int(row[0]), "name": row[1]}

        insert_result = s.execute(
            text("INSERT INTO students (name) VALUES (:name) RETURNING id, name"),
            {"name": clean_name},
        )
        new_row = insert_result.fetchone()
        s.commit()
        return {"id": int(new_row[0]), "name": new_row[1]}


def load_mastery(student_id: int, all_topics: list[str]) -> dict[str, float]:
    conn = get_db()
    mastery = {}
    with conn.session as s:
        result = s.execute(
            text("SELECT topic, mastery FROM topic_mastery WHERE student_id = :sid"),
            {"sid": student_id},
        )
        for row in result.fetchall():
            mastery[row[0]] = float(row[1])

        for topic in all_topics:
            if topic not in mastery:
                mastery[topic] = 0.0
                s.execute(
                    text(
                        "INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (:sid, :top, 0.0) "
                        "ON CONFLICT (student_id, topic) DO NOTHING"
                    ),
                    {"sid": student_id, "top": topic},
                )
        s.commit()
    return mastery


def reset_student_progress(student_id: int, all_topics: list[str]):
    conn = get_db()
    with conn.session as s:
        s.execute(
            text("DELETE FROM attempt_logs WHERE student_id = :sid"),
            {"sid": student_id},
        )
        for topic in all_topics:
            s.execute(
                text(
                    "INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (:sid, :top, 0.0) "
                    "ON CONFLICT (student_id, topic) DO UPDATE SET mastery = 0.0"
                ),
                {"sid": student_id, "top": topic},
            )
        s.commit()


def record_attempt(
    student_id: int,
    topic: str,
    template_id: str,
    is_correct: bool,
    selected_answer: str,
    new_mastery: float,
):
    conn = get_db()
    with conn.session as s:
        s.execute(
            text("""
                INSERT INTO attempt_logs (student_id, topic, template_id, is_correct, selected_answer)
                VALUES (:sid, :top, :tid, :corr, :ans)
            """),
            {
                "sid": student_id,
                "top": topic,
                "tid": template_id,
                "corr": 1 if is_correct else 0,
                "ans": selected_answer,
            },
        )
        s.execute(
            text("""
                INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (:sid, :top, :mast)
                ON CONFLICT (student_id, topic) DO UPDATE SET mastery = :mast
            """),
            {"sid": student_id, "top": topic, "mast": new_mastery},
        )
        s.commit()


# ==============================================================================
# 2. TEACHER INSTRUCTION REPOSITORY
# ==============================================================================
MINI_LESSONS = {
    "Properties of Matter": {
        "title": "Properties of Matter & Atomic Models",
        "concept": """
### 👩‍🏫 Unit 1: Atoms, Molecules, and States of Matter
* **Atoms & Elements**: An **element** is a pure substance made of only one kind of atom (like pure Oxygen or Carbon).
* **Molecules & Compounds**: When two or more different elements chemically bond together, they form a **compound** (e.g., Water is $\\text{H}_2\\text{O}$, Carbon Dioxide is $\\text{CO}_2$).
* **Why Scientists Use Models**: Atoms and molecules are far too tiny to see with the naked eye or even a standard classroom hand lens. Models help us visualize how parts fit together.
* **States of Matter**:
  * **Solid**: Tightly packed particles in a fixed lattice. Vibrates in place with definite shape and volume.
  * **Liquid**: Particles are touching but roll and slide around each other. Definite volume, takes the shape of its container.
  * **Gas**: Particles fly far apart with high energy, expanding to completely fill any container.
* **Density & Properties**: Matter can be identified by its color, particle texture (crystals vs. powder), water solubility, electrical conductivity, and density ($\\text{Density} = \\frac{\\text{Mass}}{\\text{Volume}}$).
""",
        "example": "A water molecule model shows 1 central Oxygen atom bonded to 2 smaller Hydrogen atoms. Adding another atom creates a completely different molecule!",
        "trap": "A hand lens can show sand grains or salt crystals, but it can NEVER magnify enough to see individual atoms or molecules!",
    },
    "Changes in Matter": {
        "title": "Physical vs. Chemical Changes & Conservation of Mass",
        "concept": """
### 👩‍🏫 Unit 2: Physical vs. Chemical Changes
* **Physical Change**: Changes in shape, size, texture, or state without creating a new substance. (e.g., melting ice, boiling water, dissolving salt, rolling dough, slicing peppers).
* **Chemical Change**: Rearranges atoms to form completely new substances with different chemical properties.
* **Key Clues of a Chemical Reaction**:
  1. Spontaneous formation of gas bubbles (not from boiling).
  2. Precipitate formation (a new solid formed by mixing clear liquids).
  3. Change in temperature (exothermic releases heat; endothermic absorbs heat).
  4. Noticeable color change or new odor.
* **Conservation of Mass**: In any closed system, mass is never created or destroyed. If mass decreases in an open container, gas escaped into the room!
""",
        "example": "Mixing baking soda and vinegar produces bubbling carbon dioxide gas. If done in an open beaker, the mass drops because the gas escapes into the air.",
        "trap": "Condensation on the outside of a cold glass is NOT a leak or chemical reaction—it is invisible water vapor from the warm air cooling into liquid droplets!",
    },
    "Earth's Systems": {
        "title": "Earth's Four Interacting Spheres",
        "concept": "Geosphere (solid rock/earth), Hydrosphere (liquid/frozen water), Atmosphere (air/gases), and Biosphere (all living organisms).",
        "example": "Rain from the atmosphere watering trees in the biosphere.",
        "trap": "Water vapor in the air belongs to the Hydrosphere interacting within the Atmosphere.",
    },
    "Earth's Water": {
        "title": "Global Water Reservoirs",
        "concept": "97% of Earth's water is salt ocean water. Of the remaining 3% freshwater, ~68% is frozen in glaciers and polar ice caps.",
        "example": "Less than 1% of all water on Earth is liquid freshwater available for human use.",
        "trap": "Rivers and lakes make up less than 1% of freshwater, not the majority.",
    },
    "Patterns in Space": {
        "title": "Sun Angles, Shadows, and Cycles",
        "concept": "Earth's daily 24-hour rotation causes apparent Sun movement and shadow length changes (longest at sunrise/sunset, shortest at noon).",
        "example": "A flagpole casts its shortest shadow at solar noon when the Sun is at its highest angle.",
        "trap": "Shadows do not change size because the Sun gets physically closer, but because the angle of light changes.",
    },
    "Matter & Energy in Ecosystems": {
        "title": "Energy Pyramids & Nutrient Cycling",
        "concept": "Producers convert solar energy and air (CO2) into glucose via photosynthesis. Decomposers recycle matter into soil.",
        "example": "Oak tree wood mass comes from carbon dioxide gas absorbed from the air, NOT from eating dirt.",
        "trap": "Plants take in water and soil nutrients through roots, but their dry structural mass is built from carbon in the air.",
    },
}

# ==============================================================================
# 3. DYNAMIC VECTOR DIAGRAM GENERATOR (ALL LABELS IN HIGH-CONTRAST RED)
# ==============================================================================
def render_cylinder(ax, x_offset, volume, max_vol, label):
    cyl_w, cyl_h = 1.6, 5.5
    pct = volume / max_vol
    ax.add_patch(
        patches.Ellipse(
            (x_offset + cyl_w / 2, 0.2),
            cyl_w + 1.1,
            0.45,
            facecolor="#e0e0e0",
            edgecolor="#64748b",
            lw=2,
        )
    )
    ax.add_patch(
        patches.Rectangle(
            (x_offset, 0.2),
            cyl_w,
            (cyl_h - 0.5) * pct,
            facecolor="#7b8d9e",
        )
    )
    ax.add_patch(
        patches.Rectangle(
            (x_offset, 0.2),
            cyl_w,
            cyl_h,
            facecolor="none",
            edgecolor="#94a3b8",
            lw=2.5,
        )
    )
    if pct > 0:
        ax.add_patch(
            patches.Ellipse(
                (x_offset + cyl_w / 2, 0.2 + (cyl_h - 0.5) * pct),
                cyl_w,
                0.25,
                facecolor="#5f7182",
                edgecolor="#94a3b8",
                lw=1.5,
            )
        )
    ax.add_patch(
        patches.Ellipse(
            (x_offset + cyl_w / 2, 0.2 + cyl_h),
            cyl_w,
            0.25,
            facecolor="none",
            edgecolor="#94a3b8",
            lw=2,
        )
    )
    for i in range(1, 6):
        y = 0.2 + (cyl_h - 0.5) * (i / 5.0)
        ax.plot([x_offset, x_offset + 0.35], [y, y], color=LABEL_COLOR, lw=1.8)
        ax.text(
            x_offset + 0.45,
            y - 0.1,
            f"{int((max_vol / 5) * i)}",
            fontsize=9,
            weight="bold",
            color=LABEL_COLOR,
        )
    ax.text(
        x_offset + cyl_w / 2,
        -0.7,
        label,
        ha="center",
        weight="bold",
        fontsize=15,
        color=LABEL_COLOR,
    )


def generate_diagram(diagram_type: str, params: dict) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6.5, 3.8), dpi=130)

    if diagram_type == "molecule_model":
        central_name = params.get("central_name", "Oxygen")
        central_color = params.get("central_color", "#334155")
        attached_name = params.get("attached_name", "Hydrogen")
        attached_color = params.get("attached_color", "#cbd5e1")
        count = params.get("attached_count", 2)
        bond_type = params.get("bond_type", "overlap")
        angle_spread = params.get("angle_spread", "bent")

        cx, cy, cr = 4.0, 2.2, 1.05

        if count == 2:
            if angle_spread == "linear":
                angles = [180, 0]
                dist = 2.4 if bond_type == "sticks" else 1.55
            else:
                angles = [220, 320]
                dist = 2.1 if bond_type == "sticks" else 1.45
        elif count == 3:
            angles = [210, 270, 330]
            dist = 2.0 if bond_type == "sticks" else 1.45
        elif count == 4:
            angles = [90, 180, 270, 0]
            dist = 2.1 if bond_type == "sticks" else 1.45
        else:
            angles = [220, 320]
            dist = 2.0

        if bond_type == "sticks":
            for ang in angles:
                rad = math.radians(ang)
                tx = cx + dist * math.cos(rad)
                ty = cy + dist * math.sin(rad)
                ax.plot([cx, tx], [cy, ty], color="#1e293b", lw=8, solid_capstyle="round", zorder=1)
                ax.plot([cx, tx], [cy, ty], color="#94a3b8", lw=4, solid_capstyle="round", zorder=2)

        ax.add_patch(patches.Circle((cx, cy), cr, facecolor=central_color, edgecolor="#94a3b8", lw=2, zorder=4))
        ax.text(
            cx,
            cy,
            central_name,
            ha="center",
            va="center",
            color=LABEL_COLOR,
            weight="bold",
            fontsize=12,
            zorder=6,
        )

        ar = 0.8 if bond_type == "sticks" else 0.9
        for ang in angles:
            rad = math.radians(ang)
            tx = cx + dist * math.cos(rad)
            ty = cy + dist * math.sin(rad)
            ax.add_patch(patches.Circle((tx, ty), ar, facecolor=attached_color, edgecolor="#94a3b8", lw=2, zorder=5))
            ax.text(
                tx,
                ty,
                attached_name,
                ha="center",
                va="center",
                color=LABEL_COLOR,
                weight="bold",
                fontsize=10,
                zorder=7,
            )

        ax.set_xlim(1.0, 7.0)
        ax.set_ylim(0.0, 4.4)

    elif diagram_type == "particle_flasks":
        offsets = [1.5, 4.2, 6.9]
        labels = ["A", "B", "C"]
        for idx, ox in enumerate(offsets):
            pts = [[ox - 1.1, 0.4], [ox + 1.1, 0.4], [ox + 0.3, 2.5], [ox + 0.3, 3.2], [ox - 0.3, 3.2], [ox - 0.3, 2.5]]
            ax.add_patch(patches.Polygon(pts, closed=True, facecolor="#f8fafc", edgecolor="#94a3b8", lw=2))
            ax.add_patch(patches.Rectangle((ox - 0.35, 3.15), 0.7, 0.25, facecolor="#475569", edgecolor="#64748b", lw=1.5))
            ax.text(ox, -0.2, labels[idx], ha="center", weight="bold", fontsize=15, color=LABEL_COLOR)

            if idx == 0:  # Solid
                for row in range(4):
                    for col in range(6):
                        px = ox - 0.65 + col * 0.26
                        py = 0.55 + row * 0.25
                        ax.add_patch(patches.Circle((px, py), 0.1, facecolor="#334155", edgecolor="#64748b"))
            elif idx == 1:  # Liquid
                random.seed(42)
                for _ in range(20):
                    px = ox + random.uniform(-0.7, 0.7)
                    py = random.uniform(0.5, 1.2)
                    ax.add_patch(patches.Circle((px, py), 0.1, facecolor="#64748b", edgecolor="#94a3b8"))
            elif idx == 2:  # Gas
                gas_pts = [
                    (ox - 0.4, 0.7, 0.1, 0.2),
                    (ox + 0.5, 1.1, -0.2, 0.1),
                    (ox - 0.2, 1.7, 0.1, -0.2),
                    (ox + 0.3, 2.3, -0.1, 0.2),
                    (ox, 2.8, 0.2, 0.1),
                ]
                for gx, gy, dx, dy in gas_pts:
                    ax.add_patch(patches.Circle((gx, gy), 0.11, facecolor="#94a3b8", edgecolor="#cbd5e1"))
                    ax.plot([gx, gx - dx], [gy, gy - dy], color="#cbd5e1", lw=2)

        ax.set_xlim(0, 8.5)
        ax.set_ylim(-0.5, 3.7)

    elif diagram_type == "particle_motion":
        ax.add_patch(patches.Circle((2.5, 2.0), 1.6, facecolor="#f8fafc", edgecolor="#94a3b8", lw=2.5))
        ax.text(2.5, -0.1, "Before", ha="center", weight="bold", fontsize=13, color=LABEL_COLOR)
        ax.add_patch(patches.Circle((6.5, 2.0), 1.6, facecolor="#f8fafc", edgecolor="#94a3b8", lw=2.5))
        ax.text(6.5, -0.1, "After", ha="center", weight="bold", fontsize=13, color=LABEL_COLOR)

        random.seed(101)
        for ox, speed_trails in [(2.5, False), (6.5, True)]:
            for _ in range(16):
                ang = random.uniform(0, 2 * math.pi)
                rad = random.uniform(0.2, 1.25)
                px, py = ox + rad * math.cos(ang), 2.0 + rad * math.sin(ang)
                ax.add_patch(patches.Circle((px, py), 0.11, facecolor="#475569", edgecolor="#64748b"))
                if speed_trails:
                    ax.plot([px - 0.2, px - 0.05], [py - 0.2, py - 0.05], color="#f97316", lw=2)
                    ax.plot([px + 0.05, px + 0.2], [py + 0.05, py + 0.2], color="#f97316", lw=2)
                else:
                    arc = patches.Arc((px, py), 0.35, 0.35, angle=0, theta1=20, theta2=120, color="#94a3b8", lw=1.5)
                    ax.add_patch(arc)

        ax.set_xlim(0.5, 8.5)
        ax.set_ylim(-0.5, 4.0)

    elif diagram_type == "graduated_cylinders":
        for ox, vol, lbl in [(1.8, params["vol_a"], params["label_a"]), (5.4, params["vol_b"], params["label_b"])]:
            render_cylinder(ax, ox, vol, params["max_vol"], lbl)
        ax.set(xlim=(0, 8.5), ylim=(-1.2, 6.5))

    elif diagram_type == "density_column":
        ax.add_patch(patches.Rectangle((2.5, 0.5), 3.0, 5.0, facecolor="none", edgecolor="#94a3b8", lw=3))
        colors = ["#f39c12", "#3498db", "#27ae60"]
        labels = params.get("layers", ["Top (0.8 g/mL)", "Middle (1.0 g/mL)", "Bottom (1.3 g/mL)"])
        for i in range(3):
            ax.add_patch(patches.Rectangle((2.5, 0.5 + i * 1.6), 3.0, 1.6, facecolor=colors[i], alpha=0.6, edgecolor="#94a3b8"))
            ax.text(4.0, 1.3 + i * 1.6, labels[i], ha="center", weight="bold", fontsize=12, color=LABEL_COLOR)
        ax.set(xlim=(1, 8), ylim=(0, 6.5))

    elif diagram_type == "flask_balloon":
        ax.add_patch(
            patches.Polygon(
                [[3.5, 0.5], [6.5, 0.5], [5.5, 3.2], [5.5, 4.0], [4.5, 4.0], [4.5, 3.2]],
                closed=True,
                facecolor="#eef2f7",
                edgecolor="#94a3b8",
                lw=2.5,
            )
        )
        ax.add_patch(
            patches.Polygon(
                [[3.8, 0.5], [6.2, 0.5], [5.8, 1.8], [4.2, 1.8]],
                closed=True,
                facecolor="#a0c4ff",
            )
        )
        if params.get("expanded", True):
            ax.add_patch(patches.Ellipse((5.0, 5.0), width=2.4, height=2.2, facecolor="#ff6b6b", edgecolor="#c92a2a", lw=2))
            ax.text(5.0, 5.0, "Gas Trapped", ha="center", va="center", color="white", weight="bold")
        else:
            ax.add_patch(patches.Ellipse((5.0, 4.3), width=0.8, height=0.6, facecolor="#ff6b6b", edgecolor="#c92a2a", lw=2))
        ax.text(5.0, -0.2, f"Total Mass = {params['total_mass']} g", ha="center", weight="bold", fontsize=13, color=LABEL_COLOR)
        ax.set(xlim=(1, 9), ylim=(-0.8, 6.5))

    elif diagram_type == "pan_balance":
        ax.plot([2, 8], [2.5, 2.5], color="#94a3b8", lw=4)
        ax.add_patch(patches.Polygon([[4.5, 0.5], [5.5, 0.5], [5.0, 2.5]], closed=True, facecolor="#7f8c8d"))
        ax.plot([3, 3], [1.5, 2.5], color="#94a3b8", lw=2)
        ax.plot([2.2, 3.8], [1.5, 1.5], color="#94a3b8", lw=3)
        ax.text(3, 1.8, params.get("left_label", "Object A"), ha="center", weight="bold", color=LABEL_COLOR, fontsize=12)
        ax.plot([7, 7], [1.5, 2.5], color="#94a3b8", lw=2)
        ax.plot([6.2, 7.8], [1.5, 1.5], color="#94a3b8", lw=3)
        ax.text(7, 1.8, params.get("right_label", "Object B"), ha="center", weight="bold", color=LABEL_COLOR, fontsize=12)
        ax.set(xlim=(1, 9), ylim=(0, 3.5))

    elif diagram_type == "shadow_diagram":
        sun_x, sun_y = params["sun_x"], params["sun_y"]
        pole_x, pole_h = 5.0, 3.5
        ax.plot([0, 10], [0, 0], color="#94a3b8", lw=3)
        ax.plot([pole_x, pole_x], [0, pole_h], color="#94a3b8", lw=4)
        ax.text(pole_x, -0.4, "Flagpole", ha="center", weight="bold", fontsize=11, color=LABEL_COLOR)
        slope = (pole_h - sun_y) / (pole_x - sun_x)
        shadow_tip_x = max(0.5, min(9.5, pole_x - (pole_h / slope)))
        ax.plot([pole_x, shadow_tip_x], [0, 0], color="#666", lw=7, solid_capstyle="round")
        ax.scatter([sun_x], [sun_y], color="#f39c12", s=450, zorder=5)
        ax.text(
            sun_x,
            sun_y + 0.6,
            f"Sun ({params['time_label']})",
            ha="center",
            weight="bold",
            fontsize=11,
            color=LABEL_COLOR,
        )
        ax.set(xlim=(0, 10), ylim=(-0.8, 6.5))

    ax.axis("off")
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", bbox_inches="tight", transparent=True)
    buf.seek(0)
    plt.close(fig)
    return buf


def helper_shuffle_options(correct_text, distractor_texts):
    opts = [correct_text] + distractor_texts
    random.shuffle(opts)
    letters = ["A", "B", "C", "D"]
    labeled = [f"{letters[i]}. {opt}" for i, opt in enumerate(opts)]
    return labeled, labeled[opts.index(correct_text)]


def clean_text_string(s: str) -> str:
    s = str(s).strip().lower().replace(",", "")
    s = re.sub(r"\b(grams?|g|milliliters?|ml|cubic\s+units?|units?)\b", "", s)
    return s.strip()


def check_user_answer(user_input, q: dict) -> bool:
    input_type = q.get("input_type", "radio")
    if input_type == "radio":
        return user_input == q["answer"]

    if input_type == "multiselect":
        return set(q.get("correct_answers", [])) == set(
            user_input if isinstance(user_input, list) else []
        )

    if input_type == "multi_text":
        if not isinstance(user_input, dict):
            return False
        for k, acc_list in q.get("accepted_answers_dict", {}).items():
            val = clean_text_string(user_input.get(k, ""))
            acc_cleaned = [clean_text_string(a) for a in acc_list]
            if val not in acc_cleaned:
                return False
        return True

    cleaned_user = clean_text_string(user_input)
    accepted = [clean_text_string(ans) for ans in q.get("accepted_answers", [])]
    return cleaned_user in accepted


# ==============================================================================
# 4. UNIT 1: PROPERTIES OF MATTER GENERATORS (WITH COMPLETE MOLECULE SUITE)
# ==============================================================================
def u1_molecule_model_advantages():
    molecules = [
        {"name": "water", "formula": "H2O", "c_name": "Oxygen", "c_col": "#334155", "a_name": "Hydrogen", "a_col": "#cbd5e1", "cnt": 2, "bond": "overlap", "spread": "bent"},
        {"name": "carbon dioxide", "formula": "CO2", "c_name": "Carbon", "c_col": "#1e293b", "a_name": "Oxygen", "a_col": "#f87171", "cnt": 2, "bond": "sticks", "spread": "linear"},
        {"name": "methane", "formula": "CH4", "c_name": "Carbon", "c_col": "#1e293b", "a_name": "Hydrogen", "a_col": "#cbd5e1", "cnt": 4, "bond": "sticks", "spread": "tetrahedral"},
        {"name": "ammonia", "formula": "NH3", "c_name": "Nitrogen", "c_col": "#2563eb", "a_name": "Hydrogen", "a_col": "#cbd5e1", "cnt": 3, "bond": "sticks", "spread": "pyramidal"},
        {"name": "sulfur dioxide", "formula": "SO2", "c_name": "Sulfur", "c_col": "#eab308", "a_name": "Oxygen", "a_col": "#f87171", "cnt": 2, "bond": "overlap", "spread": "bent"},
        {"name": "nitrogen dioxide", "formula": "NO2", "c_name": "Nitrogen", "c_col": "#2563eb", "a_name": "Oxygen", "a_col": "#f87171", "cnt": 2, "bond": "overlap", "spread": "bent"},
    ]
    m = random.choice(molecules)
    student = random.choice(["Lisa", "Maya", "Emma", "Claire", "Sofia"])

    correct = "The model shows parts of the molecule that are too small to see with human eyes."
    distractors = [
        f"The model proves that {m['name']} naturally exists as a solid, liquid, and gas simultaneously.",
        f"The model directly shows all observable liquid properties of {m['name']}.",
        f"The model shows how {m['name']} actively reacts with every other chemical element.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_molecule_advantage",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "diagram": "molecule_model",
        "diagram_params": {
            "central_name": m["c_name"],
            "central_color": m["c_col"],
            "attached_name": m["a_name"],
            "attached_color": m["a_col"],
            "attached_count": m["cnt"],
            "bond_type": m["bond"],
            "angle_spread": m["spread"],
        },
        "scenario": f"{student} builds a science model of a {m['name']} molecule ({m['formula']}).",
        "question": "Which statement best describes an advantage of using this model?",
        "hint": "Think about why scientists build models of atoms. Can we see atoms without models?",
        "answer": ans,
        "explanation": "Atoms and molecules are microscopic particles. Physical and computer models allow us to visualize structures that are far too small to see directly.",
    }


def u1_molecule_alteration_compound():
    molecules = [
        {"base": "water (H2O)", "added": "oxygen atom", "new": "hydrogen peroxide (H2O2)", "c_name": "Oxygen", "c_col": "#334155", "a_name": "Hydrogen", "a_col": "#cbd5e1", "cnt": 2, "bond": "overlap", "spread": "bent"},
        {"base": "carbon monoxide (CO)", "added": "oxygen atom", "new": "carbon dioxide (CO2)", "c_name": "Carbon", "c_col": "#1e293b", "a_name": "Oxygen", "a_col": "#f87171", "cnt": 2, "bond": "sticks", "spread": "linear"},
        {"base": "sulfur monoxide (SO)", "added": "oxygen atom", "new": "sulfur dioxide (SO2)", "c_name": "Sulfur", "c_col": "#eab308", "a_name": "Oxygen", "a_col": "#f87171", "cnt": 2, "bond": "overlap", "spread": "bent"},
    ]
    m = random.choice(molecules)
    student = random.choice(["Lisa", "Kevin", "Delaney", "Jamal"])
    correct = "The model now shows a completely different kind of molecule with distinct chemical properties."
    distractors = [
        "The model simply shows a slightly larger, stretched version of the original molecule.",
        "The model shows that the original molecule can change its state of matter from liquid to solid.",
        "The model shows that individual atoms have grown larger in physical size.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_molecule_alteration",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "diagram": "molecule_model",
        "diagram_params": {
            "central_name": m["c_name"],
            "central_color": m["c_col"],
            "attached_name": m["a_name"],
            "attached_color": m["a_col"],
            "attached_count": m["cnt"],
            "bond_type": m["bond"],
            "angle_spread": m["spread"],
        },
        "scenario": f"{student} modifies her model of {m['base']} by adding another circle to represent an extra {m['added']}.",
        "question": "How does adding another atom change what the scientific model represents?",
        "hint": "When you add another atom to a chemical formula, does it stay the same substance or become a new compound?",
        "answer": ans,
        "explanation": "Changing the number or arrangement of bonded atoms creates a completely different chemical compound with entirely new properties.",
    }


def u1_condensation_invisible_matter():
    student = random.choice(["Jin", "Anya", "Keisha", "Liam"])
    drink = random.choice(["ice water", "cold lemonade", "iced tea"])
    correct = "Water droplets will form and accumulate on the dry outside surface of the cold glass."
    distractors = [
        "The ice inside the glass will gradually melt into liquid water.",
        "Liquid water will slowly seep through the microscopic pores of the solid glass walls.",
        "Gas from the room will enter the liquid and turn into floating ice cubes.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_condensation_matter",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": (
            f"{student} wants to demonstrate evidence that invisible matter exists in the surrounding air. "
            f"He knows that water vapor is an invisible gas in the atmosphere that condenses into liquid when cooled. "
            f"He places a cold glass of {drink} on an outdoor picnic table on a warm sunny afternoon and observes it."
        ),
        "question": "Which observation provides direct evidence of invisible water matter existing in the surrounding air?",
        "hint": "Where did the liquid beads on the OUTSIDE of the glass come from? The glass didn't leak!",
        "answer": ans,
        "explanation": "Invisible water vapor gas floating in the warm room air touches the cold glass surface, loses thermal energy, and condenses into liquid water droplets.",
    }


def u1_hand_lens_capabilities():
    student = random.choice(["Karen", "Delaney", "Evan", "Aidan"])
    object_tested = random.choice(["granite rock", "sandstone sample", "fine sugar crystal"])
    correct = "The sample is made of individual grains, crystals, or flecks of different colors."
    distractors = [
        "The sample is composed of individual microscopic atoms bonded together.",
        "The sample contains distinct arrangements of protons, neutrons, and electrons.",
        "The exact gravitational weight of the sample in kilograms.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_hand_lens",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"{student} uses a standard laboratory hand lens (magnifying glass) to inspect a {object_tested}.",
        "question": "Which scientific observation could be directly made using a hand lens?",
        "hint": "A hand lens magnifies small visible details (like grains), but can it magnify millions of times to see atoms?",
        "answer": ans,
        "explanation": "Hand lenses magnify small visible physical textures (like mineral grains or crystals), but cannot resolve microscopic atoms or molecules.",
    }


def u1_flask_particle_states():
    student = random.choice(["Evan", "Caroline", "Jamal", "Susannah"])
    target_state = random.choice(["liquid", "gas", "solid"])
    if target_state == "solid":
        correct_letter = "A"
        desc = "tightly packed into an organized, rigid grid holding its own shape"
    elif target_state == "liquid":
        correct_letter = "B"
        desc = "resting in contact at the bottom while free to slide and take the container's shape"
    else:
        correct_letter = "C"
        desc = "widely spaced apart and bouncing rapidly to fill the entire volume"

    opts = ["A", "B", "C"]
    return {
        "template_id": "u1_flask_states",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "diagram": "particle_flasks",
        "diagram_params": {},
        "scenario": f"The illustration displays three sealed flasks (A, B, and C) modeling how particles behave in the three states of matter. {student} has a sample that is in **{target_state}** form.",
        "question": f"Which model (A, B, or C) correctly represents {student}'s {target_state} sample?",
        "hint": "Solids form neat grids at the bottom, liquids slide loosely at the bottom, and gases fly all over the flask.",
        "answer": correct_letter,
        "explanation": f"Flask {correct_letter} models a {target_state} because particles are {desc}.",
    }


def u1_kinetic_thermal_motion():
    student = random.choice(["Marcus", "Elena", "Kevin", "Zoe"])
    correct = "Thermal heat energy was added to the water, causing particles to move faster."
    distractors = [
        "The water was frozen into a solid block of crystalline ice.",
        "The container was placed inside a vacuum chamber to slow particle motion.",
        "The water was gently poured into a smaller graduated cylinder.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_thermal_motion",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "diagram": "particle_motion",
        "diagram_params": {},
        "scenario": f"During a science investigation, {student} models liquid water particles in an observation chamber 'Before' and 'After' a procedure.",
        "question": "Based on the motion marks and particle spacing shown in the diagram, what most likely happened during the investigation?",
        "hint": "Look at the 'After' diagram: notice the extra motion streaks showing particles moving with much higher speed.",
        "answer": ans,
        "explanation": "Adding thermal energy (heat) increases the kinetic energy of particles, causing them to vibrate, slide, and collide much faster.",
    }


def u1_mineral_diagnostic_matrix():
    samples = [
        {"name": "Sand (Quartz)", "texture": "grainy", "color": "tan", "sol": "no", "is_target": True},
        {"name": "Baking Soda", "texture": "soft and silky", "color": "white", "sol": "yes", "is_target": False},
        {"name": "Coarse Salt", "texture": "rough crystals", "color": "white", "sol": "yes", "is_target": False},
        {"name": "Chalk Powder", "texture": "soft powder", "color": "white", "sol": "no", "is_target": False},
    ]
    random.shuffle(samples)
    labels = ["Sample W", "Sample X", "Sample Y", "Sample Z"]
    target_idx = [i for i, s in enumerate(samples) if s["is_target"]][0]

    table_data = {
        "Sample": labels,
        "Texture": [s["texture"] for s in samples],
        "Color": [s["color"] for s in samples],
        "Soluble in Water?": [s["sol"] for s in samples],
    }

    opts = labels
    return {
        "template_id": "u1_mineral_matrix",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "table": table_data,
        "scenario": "A 5th-grade science team investigates unknown solid samples. They record their physical property observations in the data table.",
        "question": "A student knows that ordinary playground sand is tan, grainy, and does not dissolve in water. Which sample is most likely sand?",
        "hint": "Check the rows in the table: find the sample that is both 'grainy' and answered 'no' to water solubility.",
        "answer": labels[target_idx],
        "explanation": f"{labels[target_idx]} matches all properties of sand: tan color, grainy texture, and insoluble in water.",
    }


def u1_liquid_transfer_beakers():
    v = random.choice([50, 75, 100])
    correct = "The liquid will change its shape to match the larger beaker, but its volume will remain exactly the same."
    distractors = [
        "The volume of the liquid will expand to completely fill the larger beaker from top to bottom.",
        "The liquid will retain its exact original shape without spreading across the larger bottom.",
        "The liquid will immediately evaporate into a gas because the beaker has a larger surface area.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_liquid_transfer",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student pours exactly {v} mL of clear liquid from a narrow 150 mL beaker into a wide 500 mL beaker.",
        "question": "What will happen to the shape and volume of the liquid in the new beaker?",
        "hint": "Liquids take the shape of their container, but does pouring liquid create or destroy milliliters of volume?",
        "answer": ans,
        "explanation": "Liquids have a definite volume but no definite shape. They adapt to the shape of whatever container holds them while volume stays constant.",
    }


def u1_cooking_tool_conductivity():
    correct = "The silicone or rubber grip handle, because it is a thermal insulator that protects hands from heat."
    distractors = [
        "The wide stainless steel spatula blade, because metal prevents heat from transferring into food.",
        "The thin metal connecting neck, because metals are designed to block heat flow.",
        "Every part of the cooking tool conducts heat identically.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_spatula_insulator",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": "Engineers design cooking tools using multiple materials with different thermal properties. Consider a kitchen spatula with a metal blade and a silicone-coated rubber handle.",
        "question": "Which area of the cooking tool is engineered using a material that does NOT conduct heat very well, and why?",
        "hint": "Where do you hold a hot cooking tool? You want that part to insulate against heat!",
        "answer": ans,
        "explanation": "Handles are manufactured from thermal insulators (rubber, silicone, or wood) to prevent heat from traveling to the user's hand.",
    }


def u1_measuring_tools():
    tools = [
        ("pan balance", "mass in grams", "graduated cylinder", "liquid volume in milliliters"),
        ("graduated cylinder", "volume in milliliters", "spring scale", "weight in newtons"),
        ("metric ruler", "solid volume in cubic centimeters", "thermometer", "temperature in degrees Celsius"),
    ]
    pick = random.choice(tools)
    t_tool, t_prop, w_tool, w_prop = pick
    correct = f"A {t_tool}, because it is the scientific tool designed to measure {t_prop}."
    distractors = [
        f"A {w_tool}, because it is the standard tool designed to measure {t_prop}.",
        f"A {t_tool}, because its primary purpose is measuring {w_prop}.",
        "A magnifying glass, because it allows direct counting of microscopic particles.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_measuring_tools",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student plans an experiment and needs to record the exact {t_prop.split(' in ')[0]} of a mineral sample.",
        "question": "Which tool must the student select, and what scientific reason supports this choice?",
        "hint": "Think about which tool measures grams on a balance pan versus liquid volume in a cylinder.",
        "answer": ans,
        "explanation": f"A {t_tool} is used to measure {t_prop}.",
    }


def u1_density_sink_float():
    obj = random.choice([
        ("solid oak wood block", 0.75, "floats near the water surface", "its density is less than 1.0 g/mL"),
        ("pure lead sinker", 11.34, "sinks rapidly to the bottom", "its density is much greater than 1.0 g/mL"),
        ("paraffin wax cube", 0.90, "floats mostly submerged", "its density is slightly less than 1.0 g/mL"),
        ("glass marble", 2.50, "sinks directly to the bottom", "its density is greater than 1.0 g/mL"),
    ])
    name, density, behavior, reason = obj
    correct = f"It {behavior} because {reason}."
    distractors = [
        f"It {'sinks to the bottom' if 'float' in behavior else 'floats near the surface'} because heavy objects always sink regardless of density.",
        "It dissolves completely because water quickly breaks down every solid material.",
        f"It floats near the water surface because water has an identical density of {density} g/mL.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_density_sink_float",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"Fresh water has a density of exactly 1.0 g/mL. A student places a {name} with a density of {density} g/cm³ into water.",
        "question": f"What will happen to the {name}, and which reason explains this result?",
        "hint": "Compare the object's density to 1.0 g/mL. Numbers below 1.0 float; numbers above 1.0 sink.",
        "answer": ans,
        "explanation": f"Water density is 1.0 g/cm³. {name.capitalize()} has a density of {density} g/cm³, so {reason}.",
    }


def u1_density_column_visual():
    correct = "Corn syrup settles on the bottom due to highest density, while alcohol floats on top with lowest density."
    distractors = [
        "Corn syrup settles on the bottom because it was poured into the cylinder first.",
        "Rubbing alcohol floats on top because all liquids with high density rise to the surface.",
        "Water pushes the syrup to the bottom because water exerts a magnetic downward force on sugar.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_density_column",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "diagram": "density_column",
        "diagram_params": {"layers": ["Top: Alcohol", "Middle: Water", "Bottom: Syrup"]},
        "scenario": "A student layers equal volumes of rubbing alcohol, colored water, and corn syrup in a cylinder.",
        "question": "Which scientific principle explains why these liquids remain separated in these distinct layers?",
        "hint": "Liquids stack based on density: densest on the bottom, least dense on top.",
        "answer": ans,
        "explanation": "Liquids layer by density. The densest liquid sinks to the bottom, and the least dense liquid floats on top.",
    }


def u1_magnetism_metals():
    items = [
        ("iron nail", "steel paperclip", "copper wire", "aluminum foil strip"),
        ("cobalt pin", "nickel washer", "plastic button", "rubber band"),
    ]
    mag1, mag2, non1, non2 = random.choice(items)
    correct = f"{mag1.capitalize()} and {mag2}, because they are made of magnetic metals (iron, nickel, or cobalt)."
    distractors = [
        f"{non1.capitalize()} and {non2}, because every metallic object is naturally attracted to magnets.",
        "All four listed items, because magnetic fields attract all solid materials equally.",
        "None of the items, because magnets only attract objects carrying live electrical current.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_magnetism",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student tests four objects with a bar magnet: a {mag1}, a {mag2}, a {non1}, and a {non2}.",
        "question": "Which items will stick to the magnet?",
        "hint": "Only iron, nickel, cobalt, and steel are magnetic. Copper and aluminum are not magnetic!",
        "answer": ans,
        "explanation": "Only ferromagnetic metals (iron, nickel, cobalt, and steel) are attracted to magnets.",
    }


def u1_solubility_saturation():
    solute = random.choice(["table salt", "cane sugar", "potassium chloride"])
    max_g = random.choice([35, 40])
    added_g = max_g + 15
    correct = f"Solid {solute} ({added_g - max_g} g) will sit on the bottom because the solution reached its saturation point."
    distractors = [
        f"All {added_g} grams will dissolve completely because liquids can hold an infinite amount of solute.",
        "The water will instantly freeze solid because dissolving solute absorbs all heat energy.",
        f"The extra {added_g - max_g} grams of {solute} will transform directly into carbon dioxide gas.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_solubility",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"At room temperature, exactly {max_g} g of {solute} can dissolve in 100 mL of water before saturation. A student adds {added_g} g of {solute} to 100 mL of water and stirs.",
        "question": "What will the student observe after stirring?",
        "hint": "Once a solution is saturated, it cannot dissolve any more solute. What happens to the extra solid?",
        "answer": ans,
        "explanation": f"At saturation ({max_g} g), no more solute can dissolve. The extra {added_g - max_g} g settles at the bottom.",
    }


def u1_gas_has_mass():
    deflated = random.randint(3, 4)
    inflated = deflated + 2
    correct = f"Air has mass (the added air weighed {inflated - deflated} g), proving that gases are made of matter."
    distractors = [
        "Air has zero mass; the scale showed more weight because stretching rubber creates new atoms.",
        "The inflated balloon weighed more because warm room air exerts magnetic pressure on scales.",
        "Gases have measurable volume, but science proves they never possess any measurable mass.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_gas_mass",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student measures a deflated balloon ({deflated}.0 g). She pumps air into it and seals it; the scale now reads {inflated}.0 g.",
        "question": "What fundamental science concept does this experiment prove?",
        "hint": "Matter has mass and takes up space. Did adding invisible gas make the balloon heavier?",
        "answer": ans,
        "explanation": "Air is a gas, and gas is matter. Pumping air inside adds mass, proving gas has mass.",
    }


def u1_graduated_cylinder_volume():
    v1 = random.choice([15, 20])
    v2 = random.choice([35, 40])
    diff = v2 - v1
    correct = f"Sample Y has a volume of {v2} mL, which is {diff} mL greater than Sample X ({v1} mL)."
    distractors = [
        f"Sample X has a volume of {v1} mL, which is {diff} mL greater than Sample Y ({v2} mL).",
        "Both samples have identical volumes because both graduated cylinders reach the 50 mL line.",
        "Volume cannot be determined from graduated cylinders without knowing each liquid's mass.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_cyl_vol",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "diagram": "graduated_cylinders",
        "diagram_params": {
            "vol_a": v1,
            "vol_b": v2,
            "max_vol": 50,
            "label_a": "X",
            "label_b": "Y",
        },
        "scenario": "A student measures liquid samples X and Y in graduated cylinders.",
        "question": "What do the graduated cylinder readings show about the volumes of Sample X and Sample Y?",
        "hint": "Read the number right at the liquid meniscus line for cylinder X and cylinder Y, then subtract.",
        "answer": ans,
        "explanation": f"Sample X reads {v1} mL and Sample Y reads {v2} mL. The difference is {diff} mL.",
    }


def u1_pan_balance_comparison():
    correct = "Object B has greater mass than Object A, causing its side of the balance beam to tip downward."
    distractors = [
        "Object A has greater mass than Object B, causing its side of the balance beam to rise upward.",
        "Both objects have identical mass because both objects are resting on the same balance.",
        "The pan balance measures volume, so Object B must take up more space than Object A.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_pan_bal",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "diagram": "pan_balance",
        "diagram_params": {"left_label": "A (50g)", "right_label": "B (75g)"},
        "scenario": "A student places Object A (50 g) and Object B (75 g) on opposite pans of an equal-arm balance.",
        "question": "What happens to the balance beam, and what does it reveal about the two objects?",
        "hint": "Gravity pulls harder on heavier objects. Which side tips down?",
        "answer": ans,
        "explanation": "A pan balance compares mass. The pan holding the heavier mass (Object B) tips downward.",
    }


# ==============================================================================
# 5. UNIT 2: CHANGES IN MATTER (EXPANDED DIVERSE GENERATOR BANK)
# ==============================================================================
def u2_pizza_recipe_changes():
    steps = [
        ("Rolling dough flat with a rolling pin", "Physical change", "it only changes the shape and thickness of the dough"),
        ("Slicing bell peppers and onions into strips", "Physical change", "it only changes the size of the vegetable pieces"),
        ("Grating a block of mozzarella cheese into shreds", "Physical change", "it alters the size and form of the solid cheese without making a new substance"),
        ("Yeast fermenting sugar into bubbling carbon dioxide gas causing dough to rise", "Chemical change", "living yeast produces a new gas substance"),
        ("Baking raw dough in an oven until it turns into a browned crust", "Chemical change", "heat creates brand-new browned compounds and flavors"),
        ("Baking cheese until it browns and forms new crisp crusts", "Chemical change", "proteins and sugars chemically react under high heat"),
    ]
    pick = random.choice(steps)
    correct = f"{pick[1]}, because {pick[2]}."
    wrong_type = "Chemical change" if pick[1] == "Physical change" else "Physical change"
    distractors = [
        f"{wrong_type}, because mass was permanently lost during the step.",
        f"{wrong_type}, because thermal energy was added.",
        f"{pick[1]}, because all matter was destroyed during the step.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u2_pizza_recipe",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student helps prepare homemade pizza. Consider this specific step in the recipe: **{pick[0]}**.",
        "question": "How is this step classified, and what is the scientific justification?",
        "hint": "Did the step just change size/shape (physical), or did it create brand-new substances by baking/bubbling (chemical)?",
        "answer": ans,
        "explanation": f"{pick[0]} is a {pick[1]} because {pick[2]}.",
    }


def u2_color_reaction_conservation():
    student = random.choice(["Sophia", "Jamal", "Elena", "Aidan"])
    mx = random.randint(110, 160)
    my = random.randint(30, 60)
    mtot = mx + my
    cx = random.choice(["clear", "blue", "red"])
    cy = random.choice(["colorless", "yellow", "white"])
    cnew = "green" if (cx == "blue" and cy == "yellow") else "purple"

    table_data = {
        "Substance": ["Reactant X", "Reactant Y", "Combined Mixture XY"],
        "Color": [cx, cy, cnew],
        "Mass on Scale": [f"{mx} g", f"{my} g", f"{mtot} g"],
    }
    correct = "The Law of Conservation of Mass states that matter cannot be created or destroyed in a reaction."
    distractors = [
        "A physical change occurred, which automatically doubles the weight of liquids.",
        "The reaction destroyed the yellow pigment atoms, converting them into extra mass.",
        "Color changes only happen when extra air enters a solution.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u2_color_conservation",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "table": table_data,
        "scenario": (
            f"{student} measures the mass of Substance X ({mx} g) and Substance Y ({my} g). "
            f"When mixed, an unexpected color change ({cnew}) appears, indicating a chemical reaction. "
            f"She measures the final mass of Mixture XY and records {mtot} g."
        ),
        "question": f"Which fundamental law explains why the mass of X ({mx} g) plus Y ({my} g) equals the exact mass of XY ({mtot} g)?",
        "hint": "Matter cannot be created or destroyed: Mass of Reactants = Mass of Products.",
        "answer": ans,
        "explanation": f"By the Law of Conservation of Mass, the total mass of reactants ({mx}g + {my}g = {mtot}g) equals the total mass of products.",
    }


def u2_open_beaker_gas_table():
    student = random.choice(["Sophia", "Claire", "Jamal", "Noah"])
    mw = random.randint(90, 130)
    mz = random.randint(25, 45)
    loss = random.randint(3, 7)
    mfinal = (mw + mz) - loss

    table_data = {
        "Substance": ["Substance W", "Substance Z", "Final Mixture WZ"],
        "Mass on Scale": [f"{mw} g", f"{mz} g", f"{mfinal} g"],
    }
    correct = "The reaction produced a gas, which escaped into the atmosphere because the container was open."
    distractors = [
        "The chemical reaction destroyed atoms during the bubbling process.",
        "The physical change caused particles to shrink in physical mass.",
        "Liquid water absorbed the solid powder and made it weightless.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u2_open_table_gas",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "table": table_data,
        "scenario": (
            f"{student} combines Substance W ({mw} g) and Substance Z ({mz} g) in an open beaker. "
            f"Vigorous bubbling occurs. When bubbling ceases, the final mass is {mfinal} g."
        ),
        "question": f"Why is the mass of W and Z combined ({mw + mz} g) greater than the mass of the final mixture ({mfinal} g)?",
        "hint": "Where did the bubbles go? The beaker had no lid!",
        "answer": ans,
        "explanation": f"The {loss} grams of missing mass did not disappear; it escaped into the surrounding room air as gas bubbles.",
    }


def u2_weathered_tool_rusting():
    tool = random.choice(["steel hammer", "iron garden shears", "steel trowel"])
    correct = "Rust (iron oxide), which is a chemical change caused by iron reacting with oxygen and water."
    distractors = [
        "Paint chipping, which is a purely physical change of state.",
        "Evaporation, which is a physical change of state.",
        "Melted metal, which is an irreversible chemical change.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u2_rusting_hammer",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A new {tool} with a shiny metallic head was accidentally left outside in the damp grass all spring. By June, the metal head is coated in a rough, reddish-brown crust.",
        "question": "The weathered metal shows evidence of which process, and how is it classified?",
        "hint": "Reddish-brown crust on iron left outside is rust. Is rusting physical or chemical?",
        "answer": ans,
        "explanation": "Rusting is a chemical change that occurs when iron chemically reacts with oxygen and water to form a brand-new compound (iron oxide).",
    }


def u2_chemical_evidence_multiselect():
    pairs = [
        ("Release of thermal heat or light", True),
        ("Spontaneous temperature change without heating or cooling", True),
        ("Formation of unexpected gas bubbles without boiling", True),
        ("Permanent unexpected color change", True),
        ("Formation of an insoluble solid precipitate", True),
        ("Cutting a solid into smaller pieces", False),
        ("Melting an ice cube into liquid water", False),
        ("Dissolving sugar crystals into warm water", False),
    ]
    random.shuffle(pairs)
    sample = pairs[:5]
    if not any(p[1] for p in sample):
        sample[0] = pairs[0]

    opts = [p[0] for p in sample]
    correct_opts = [p[0] for p in sample if p[1]]
    return {
        "template_id": "u2_chem_evidence_multi",
        "topic": "Changes in Matter",
        "input_type": "multiselect",
        "options": opts,
        "correct_answers": correct_opts,
        "scenario": "A 5th-grade science class investigates how to distinguish between physical and chemical changes.",
        "question": "Which observations provide direct evidence that a **chemical change** has occurred? (Choose all that apply)",
        "hint": "Look for clues that indicate new substances are forming: heat, gas bubbles, new solids, or color shifts!",
        "explanation": "Chemical changes form new substances and are indicated by heat/light release, gas production, precipitate formation, and unexpected color changes.",
    }


def u2_freezer_mass_conservation():
    student = random.choice(["Keisha", "Liam", "Carlos", "Maya"])
    m = random.choice([450, 680, 850, 920])
    correct = f"Mass before freezer: {m} grams | Mass after freezer: {m} grams"
    distractors = [
        f"Mass before freezer: {m} grams | Mass after freezer: {m - 150} grams",
        f"Mass before freezer: {m} grams | Mass after freezer: {m + 100} grams",
        f"Mass before freezer: {m} grams | Mass after freezer: {m // 2} grams",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u2_freezer_mass",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": (
            f"{student} records the mass of a sealed bottle of liquid substance X ({m} grams). "
            f"She places the sealed bottle into a freezer until it freezes completely solid. "
            f"She removes the frozen bottle and measures its mass on the digital balance again."
        ),
        "question": "Which set of data did the student most likely record after freezing?",
        "hint": "Freezing is a physical change of state inside a sealed container. Does changing state destroy or add mass?",
        "answer": ans,
        "explanation": "Freezing is a physical change. In a closed container, matter cannot enter or leave, so the mass before freezing equals the mass after freezing.",
    }


def u2_closed_balloon_gas():
    v = random.randint(60, 90)
    b = random.randint(10, 20)
    f = random.choice([50, 60, 75])
    total = v + b + f

    opts, ans = helper_shuffle_options(
        f"Exactly {total} grams, because the sealed balloon prevents gas produced by the reaction from escaping.",
        [
            f"Only {v + b} grams, because the glass flask loses its mass during a chemical reaction.",
            f"Less than {total} grams, because gases produced in chemical reactions have zero measurable mass.",
            f"{total - b} grams, because the solid baking soda atoms were converted directly into energy.",
        ],
    )
    return {
        "template_id": "u2_balloon_gas",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "diagram": "flask_balloon",
        "diagram_params": {"total_mass": total, "expanded": True},
        "scenario": (
            f"A student measures an empty flask and balloon ({f} g). She pours in {v} g of vinegar "
            f"and places {b} g of baking soda inside the balloon before sealing it tightly over the neck of the flask. "
            f"The digital scale confirms the starting combined mass is {total} g ({f}g + {v}g + {b}g). "
            f"She tips the balloon, dumping the powder into the liquid. Vigorous bubbling occurs, "
            f"inflating the balloon with gas."
        ),
        "question": "What will the scale read after the bubbling stops while the balloon remains sealed?",
        "hint": f"Add the parts: {f} g (flask) + {v} g (vinegar) + {b} g (baking soda) = {total} g. Did any gas escape the sealed system?",
        "answer": ans,
        "explanation": f"In a closed system, matter cannot escape. The total remains {f} g + {v} g + {b} g = {total} g.",
    }


def u2_conservation_dissolving():
    water_g = random.randint(120, 200)
    sugar_g = random.randint(15, 35)
    total = water_g + sugar_g

    opts, ans = helper_shuffle_options(
        f"Exactly {total} grams, because the dissolved sugar molecules still exist inside the solution.",
        [
            f"{water_g} grams, because the solid sugar was destroyed when it dissolved into clear liquid.",
            f"{total + 10} grams, because stirring liquid vigorously adds atmospheric weight to the cup.",
            f"{sugar_g} grams, because the water evaporated immediately as soon as sugar touched it.",
        ],
    )
    return {
        "template_id": "u2_dissolving",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": (
            f"A student places an empty cup on a scale, tares it to 0 g, and adds {water_g} g of warm water. "
            f"She then adds {sugar_g} g of dry sugar crystals. The display confirms the starting contents "
            f"equal {total} g ({water_g}g + {sugar_g}g). She stirs until every crystal dissolves completely."
        ),
        "question": "What is the total mass of the clear sugar-water solution on the scale?",
        "hint": f"Add the parts together: {water_g} g water + {sugar_g} g sugar. Dissolving does not destroy mass!",
        "answer": ans,
        "explanation": f"Conservation of mass: {water_g} g water + {sugar_g} g sugar = {total} g total solution.",
    }


def u2_multistep_mixture_separation():
    iron = random.randint(15, 25)
    sand = random.randint(30, 45)
    salt = random.randint(20, 30)
    total = iron + sand + salt

    table = {
        "Step": [
            "1. Pass magnet over dry mixture",
            "2. Add water and stir",
            "3. Pour through filter paper",
            "4. Boil the filtered liquid",
        ],
        "Result": [
            f"Iron filings separated ({iron} g)",
            "Salt dissolves into the water",
            f"Sand trapped on filter ({sand} g)",
            f"Pure salt recovered ({salt} g)",
        ],
    }
    opts, ans = helper_shuffle_options(
        f"All {total} grams of original substances are recovered because separating mixtures uses physical properties without destroying matter.",
        [
            f"Only {sand + salt} grams are recovered because magnets destroy the mass of metals.",
            "The salt was permanently destroyed in Step 2 when it dissolved into clear liquid water.",
            "Mass decreased because paper filters remove microscopic atoms from physical existence.",
        ],
    )
    return {
        "template_id": "u2_mix_sep",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "table": table,
        "scenario": (
            f"A student measures out {iron} g of iron filings, {sand} g of playground sand, "
            f"and {salt} g of table salt, creating a mixture with a verified total mass of "
            f"{total} g ({iron}g + {sand}g + {salt}g). She separates the mixture using the four-step procedure below:"
        ),
        "question": "What does this experiment demonstrate about mixtures and the Law of Conservation of Mass?",
        "hint": f"Add up the recovered amounts: {iron} g + {sand} g + {salt} g = {total} g. Was any matter lost?",
        "answer": ans,
        "explanation": f"Every component was recovered: {iron}g + {sand}g + {salt}g = {total}g. Physical separation preserves all mass.",
    }


def u2_precipitate_indicator():
    opts, ans = helper_shuffle_options(
        "A chemical change, because two clear liquids reacted to form an insoluble solid precipitate.",
        [
            "A physical change, because mixing two liquids together always produces a solid naturally.",
            "A phase change, because the liquid mixture instantly froze into solid ice at room temperature.",
            "No change occurred, because the two clear liquids simply separated like oil and vinegar.",
        ],
    )
    return {
        "template_id": "u2_precipitate",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": "A student mixes two clear, colorless solutions. Instantly, the mixture turns cloudy white, and solid white particles settle to the bottom.",
        "question": "What kind of change took place, and what evidence supports this conclusion?",
        "hint": "When two clear liquids form a brand-new solid that sinks, that solid is called a precipitate. That proves a chemical reaction happened!",
        "answer": ans,
        "explanation": "Forming an insoluble solid precipitate from two clear liquids is definitive proof of a chemical change.",
    }


# ==============================================================================
# 6. OTHER TOPICS (EARTH SYSTEMS, WATER, SPACE, ECOSYSTEMS)
# ==============================================================================
def gen_patterns_in_space_factory():
    times = [
        {"label": "8:30 AM (Early Morning)", "sun_x": 1.5, "sun_y": 2.2, "is_noon": False},
        {"label": "12:15 PM (Solar Noon)", "sun_x": 5.0, "sun_y": 5.8, "is_noon": True},
        {"label": "4:45 PM (Late Afternoon)", "sun_x": 8.5, "sun_y": 2.4, "is_noon": False},
    ]
    pick = random.choice(times)
    if pick["is_noon"]:
        correct = "The shadow is at its shortest because the Sun reaches its highest apparent point in the sky."
        distractors = [
            "The shadow is at its longest because the Sun is furthest from Earth.",
            "The shadow points directly West because Earth reversed its spin.",
            "Shadows only form during morning hours.",
        ]
    else:
        correct = "The shadow is long because the Sun is at a low angle near the horizon."
        distractors = [
            "The shadow is short because the Sun is overhead.",
            "The shadow points toward the Sun instead of away from it.",
            "Earth stopped rotating.",
        ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "space_shadow_patterns",
        "topic": "Patterns in Space",
        "input_type": "radio",
        "options": opts,
        "diagram": "shadow_diagram",
        "diagram_params": pick,
        "scenario": f"A student monitors a flagpole shadow at {pick['label']}.",
        "question": f"Based on the Sun's position at {pick['label']}, which statement accurately explains the shadow formed?",
        "hint": "Low Sun in sky = long shadow. High Sun overhead = short shadow.",
        "answer": ans,
        "explanation": "Earth's daily 24-hour rotation causes the Sun to appear low at morning/evening (long shadows) and high around noon (short shadows).",
    }


def gen_earths_systems_factory():
    events = [
        (
            "A river carves a deep canyon through rock layers over millions of years.",
            "Hydrosphere (moving river water) and Geosphere (canyon rock layers)",
            "Hydrosphere and Geosphere",
        ),
        (
            "Forest pine trees absorb carbon dioxide and release oxygen during the day.",
            "Biosphere (living pine trees) and Atmosphere (surrounding air gases)",
            "Biosphere and Atmosphere",
        ),
        (
            "Tree roots wedge into a crack in a granite boulder and split it.",
            "Biosphere (living tree roots) and Geosphere (granite rock)",
            "Biosphere and Geosphere",
        ),
    ]
    pick = random.choice(events)
    correct = pick[1]
    distractors = [
        "Atmosphere (air pressure) and Geosphere (solid rock layers)",
        "Cryosphere (frozen polar ice) and Biosphere (living organisms)",
        "Hydrosphere (liquid ocean water) and Biosphere (living animals)",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "sys_sphere_interactions",
        "topic": "Earth's Systems",
        "input_type": "radio",
        "options": opts,
        "scenario": f"Consider this natural phenomenon: **{pick[0]}**",
        "question": "Which two of Earth's four spheres interact during this event?",
        "hint": "Break it down: Water = Hydro, Rock = Geo, Air = Atmo, Life = Bio.",
        "answer": ans,
        "explanation": f"This process is an interaction between the {pick[2]}.",
    }


def gen_earths_water_factory():
    correct = "Frozen inside solid polar ice caps and mountain glaciers (about 68%)."
    distractors = [
        "Flowing freely through freshwater rivers, streams, and lakes.",
        "Floating in the atmosphere as clouds and invisible water vapor.",
        "Stored in the vast saltwater oceans and coastal estuaries.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "water_freshwater_res",
        "topic": "Earth's Water",
        "input_type": "radio",
        "options": opts,
        "scenario": "A scientist reviews data tables showing all freshwater sources on Earth.",
        "question": "Where is the largest reservoir of Earth's FRESHWATER stored?",
        "hint": "Most freshwater is frozen solid at the North and South poles!",
        "answer": ans,
        "explanation": "About 68% of all freshwater on Earth is frozen in glaciers and polar ice caps.",
    }


def gen_ecosystems_factory():
    chains = [
        {
            "chain": "Sun ➔ Phytoplankton ➔ Krill ➔ Baleen Whale",
            "q": "What is the primary source of energy that sustains this entire marine food chain?",
            "c": "Solar energy captured by phytoplankton through photosynthesis.",
            "d": [
                "Thermal heat radiated from deep ocean vents.",
                "Nutrients produced directly by the baleen whale.",
                "Salt dissolved in ocean water.",
            ],
            "h": "Almost all food chains on Earth start with the same source of light energy.",
        },
        {
            "chain": "Oak Leaves ➔ Caterpillar ➔ Songbird ➔ Decomposers (Fungi)",
            "q": "What essential role do decomposers perform in this ecosystem?",
            "c": "Breaking down dead matter to recycle nutrients back into the soil for plants.",
            "d": [
                "Producing oxygen gas for forest animals through photosynthesis.",
                "Hunting live insect populations to keep ecosystems balanced.",
                "Absorbing solar energy to produce glucose sugars for carnivores.",
            ],
            "h": "Decomposers recycle dead material back into plant food in the dirt.",
        },
    ]
    pick = random.choice(chains)
    opts, ans = helper_shuffle_options(pick["c"], pick["d"])
    return {
        "template_id": "eco_food_chains",
        "topic": "Matter & Energy in Ecosystems",
        "input_type": "radio",
        "options": opts,
        "scenario": f"Consider this energy flow model: **{pick['chain']}**",
        "question": pick["q"],
        "hint": pick["h"],
        "answer": ans,
        "explanation": f"Correct: {pick['c']}",
    }


# ==============================================================================
# 7. MASTER GENERATOR REGISTRY (UNITS 1 - 6)
# ==============================================================================
GENERATORS = [
    # Unit 1: Properties of Matter
    u1_molecule_model_advantages,
    u1_molecule_alteration_compound,
    u1_condensation_invisible_matter,
    u1_hand_lens_capabilities,
    u1_flask_particle_states,
    u1_kinetic_thermal_motion,
    u1_mineral_diagnostic_matrix,
    u1_liquid_transfer_beakers,
    u1_cooking_tool_conductivity,
    u1_measuring_tools,
    u1_density_sink_float,
    u1_density_column_visual,
    u1_magnetism_metals,
    u1_solubility_saturation,
    u1_gas_has_mass,
    u1_graduated_cylinder_volume,
    u1_pan_balance_comparison,
    # Unit 2: Changes in Matter
    u2_pizza_recipe_changes,
    u2_color_reaction_conservation,
    u2_open_beaker_gas_table,
    u2_weathered_tool_rusting,
    u2_chemical_evidence_multiselect,
    u2_freezer_mass_conservation,
    u2_closed_balloon_gas,
    u2_conservation_dissolving,
    u2_multistep_mixture_separation,
    u2_precipitate_indicator,
    # Other Curriculum Topics
    gen_patterns_in_space_factory,
    gen_earths_systems_factory,
    gen_earths_water_factory,
    gen_ecosystems_factory,
]

TOPIC_TO_GENERATORS = {}
for g in GENERATORS:
    sample_q = g()
    TOPIC_TO_GENERATORS.setdefault(sample_q["topic"], []).append(g)

ALL_TOPICS = sorted(list(TOPIC_TO_GENERATORS.keys()))
init_db()

# ==============================================================================
# 8. STREAMLIT APPLICATION UI
# ==============================================================================
st.set_page_config(
    page_title="Savvas Elevate Science Homeschool Tutor",
    page_icon="🔬",
    layout="wide",
)

for key in ["student", "current_q", "answered", "feedback"]:
    if key not in st.session_state:
        st.session_state[key] = None

for key in ["mastery", "recent_templates"]:
    if key not in st.session_state:
        st.session_state[key] = {} if key == "mastery" else []

if "q_counter" not in st.session_state:
    st.session_state.q_counter = 0

# --- Sidebar UI ---
with st.sidebar:
    st.header("👤 Student Profile")
    existing_students = list_students()
    profile_mode = st.radio(
        "Profile Action:",
        ["Select Existing Student", "Add New Student"],
        horizontal=True,
    )

    if profile_mode == "Select Existing Student":
        if existing_students:
            names = [s["name"] for s in existing_students]
            idx = (
                names.index(st.session_state.student["name"])
                if st.session_state.student and st.session_state.student["name"] in names
                else 0
            )
            chosen_name = st.selectbox("Choose Student:", names, index=idx)
            if st.button("Load Profile"):
                p = get_or_create_student(chosen_name)
                st.session_state.update({
                    "student": p,
                    "mastery": load_mastery(p["id"], ALL_TOPICS),
                    "current_q": None,
                    "recent_templates": [],
                    "answered": False,
                    "feedback": None,
                })
                st.rerun()
        else:
            st.info("No saved students found. Please choose 'Add New Student'.")
    else:
        new_name = st.text_input("New Student Name:")
        if st.button("Create & Start") and new_name.strip():
            p = get_or_create_student(new_name)
            st.session_state.update({
                "student": p,
                "mastery": load_mastery(p["id"], ALL_TOPICS),
                "current_q": None,
                "recent_templates": [],
                "answered": False,
                "feedback": None,
            })
            st.rerun()

    if st.session_state.student:
        st.caption(f"Active Student: **{st.session_state.student['name']}**")
        if st.button("🔄 Reset This Student to 0%", type="secondary"):
            reset_student_progress(st.session_state.student["id"], ALL_TOPICS)
            st.session_state.update({
                "mastery": {t: 0.0 for t in ALL_TOPICS},
                "recent_templates": [],
                "current_q": None,
                "answered": False,
                "feedback": None,
            })
            st.toast("Progress reset to 0%!", icon="🔄")
            st.rerun()

    st.markdown("---")
    selected_topics = st.multiselect(
        "🎯 Focus Units for Today:",
        ALL_TOPICS,
        default=ALL_TOPICS,
    )

    st.markdown("---")
    if st.session_state.student:
        st.header("📊 Current Topic Mastery")
        for topic in selected_topics:
            score = st.session_state.mastery.get(topic, 0.0)
            st.write(f"**{topic}** ({int(score * 100)}%)")
            st.progress(score)


# --- Adaptive Question Dispatcher ---
def pick_next_question():
    if not selected_topics:
        st.session_state.current_q = None
        return

    funcs = [f for t in selected_topics for f in TOPIC_TO_GENERATORS.get(t, [])]
    if not funcs:
        st.session_state.current_q = None
        return

    cooling = [f for f in funcs if f.__name__ not in st.session_state.recent_templates]
    if not cooling:
        last = (
            st.session_state.recent_templates[-1]
            if st.session_state.recent_templates
            else None
        )
        cooling = [f for f in funcs if f.__name__ != last] or funcs
        st.session_state.recent_templates = []

    weights = []
    for f in cooling:
        dummy = f()
        score = st.session_state.mastery.get(dummy["topic"], 0.0)
        weights.append(max(0.1, 1.0 - score))

    chosen_func = random.choices(cooling, weights=weights, k=1)[0]
    st.session_state.current_q = chosen_func()
    st.session_state.answered = False
    st.session_state.feedback = None
    st.session_state.q_counter += 1

    st.session_state.recent_templates.append(chosen_func.__name__)
    if len(st.session_state.recent_templates) > 8:
        st.session_state.recent_templates.pop(0)


# --- Main UI Area ---
st.title("🔬 Savvas Elevate Science Tutor")

if not st.session_state.student:
    st.info("👈 Select or create a student profile in the sidebar to begin.")
    st.stop()

if not selected_topics:
    st.warning("👈 Please select at least one unit topic in the sidebar.")
    st.stop()

if (
    st.session_state.current_q is None
    or st.session_state.current_q["topic"] not in selected_topics
):
    pick_next_question()

q = st.session_state.current_q
if q is None:
    st.warning("No questions available for the selected unit.")
    st.stop()

# ==============================================================================
# ADAPTIVE TEACHER INTERVENTION: TRIGGER MINI-LESSON ON LOW MASTERY (< 40%)
# ==============================================================================
current_topic_mastery = st.session_state.mastery.get(q["topic"], 0.0)

if current_topic_mastery < 0.40 and q["topic"] in MINI_LESSONS:
    lesson_info = MINI_LESSONS[q["topic"]]
    with st.expander(
        f"📖 **Teacher Mode Activated: {lesson_info['title']}** (Click to Review Concepts)",
        expanded=False,
    ):
        st.markdown(lesson_info["concept"])
        st.markdown("#### 📝 Worked Step-by-Step Example")
        st.info(lesson_info["example"])
        st.warning(f"⚠️ **Watch Out for This Common Mistake:** {lesson_info['trap']}")

st.caption(f"Curriculum Unit: **{q['topic']}** | Skill Code: `{q['template_id']}`")
st.info(f"**Scenario / Context:**\n\n{q['scenario']}")

if "table" in q:
    st.write("**Reference Data Table:**")
    st.dataframe(pd.DataFrame(q["table"]), hide_index=True)

if "diagram" in q:
    img_buffer = generate_diagram(q["diagram"], q.get("diagram_params", {}))
    st.image(img_buffer, width=480)

if "hint" in q and not st.session_state.answered:
    with st.expander("💡 Need a Teacher Hint? Click here before answering!"):
        st.info(q["hint"])

st.write(f"### {q['question']}")

form_key = f"form_{q['template_id']}_{st.session_state.q_counter}"
with st.form(key=form_key):
    input_mode = q.get("input_type", "radio")
    user_response = None

    if input_mode == "radio":
        user_response = st.radio(
            "Choose the correct answer:",
            q["options"],
            index=None,
            disabled=st.session_state.answered,
        )

    elif input_mode == "multiselect":
        st.write("**Choose all that apply:**")
        selected_boxes = []
        for opt in q["options"]:
            if st.checkbox(opt, key=f"chk_{opt}_{st.session_state.q_counter}"):
                selected_boxes.append(opt)
        user_response = selected_boxes

    submit = st.form_submit_button(
        "Check Answer", disabled=st.session_state.answered
    )

    if submit and not st.session_state.answered:
        has_input = False
        if input_mode == "multiselect":
            has_input = len(user_response) > 0
        elif user_response is not None and str(user_response).strip() != "":
            has_input = True

        if has_input:
            st.session_state.answered = True
            is_correct = check_user_answer(user_response, q)
            curr_score = st.session_state.mastery.get(q["topic"], 0.0)
            new_score = (
                min(1.0, curr_score + random.uniform(0.06, 0.12))
                if is_correct
                else max(0.0, curr_score - random.uniform(0.08, 0.15))
            )

            correct_ans_display = q.get("answer", "")
            if input_mode == "multiselect":
                correct_ans_display = ", ".join(q.get("correct_answers", []))

            st.session_state.feedback = {
                "type": "success" if is_correct else "error",
                "msg": (
                    f"🎉 **Correct!**\n\n{q['explanation']}"
                    if is_correct
                    else f"❌ **Not quite.**\n\n**Correct Answer:** {correct_ans_display}\n\n💡 **Explanation:** {q['explanation']}"
                ),
            }

            st.session_state.mastery[q["topic"]] = new_score
            record_attempt(
                st.session_state.student["id"],
                q["topic"],
                q["template_id"],
                is_correct,
                str(user_response),
                new_score,
            )

if st.session_state.feedback:
    if st.session_state.feedback["type"] == "success":
        st.success(st.session_state.feedback["msg"])
    else:
        st.error(st.session_state.feedback["msg"])

if st.session_state.answered and st.button("Next Question ➡️"):
    pick_next_question()
    st.rerun()

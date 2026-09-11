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
# 2. TEACHER INSTRUCTION REPOSITORY: SAVVAS 5TH GRADE SCIENCE
# ==============================================================================
MINI_LESSONS = {
    "Properties of Matter": {
        "title": "Properties of Matter Foundations",
        "concept": """
### 👩‍🏫 Unit 1: What Is Matter & How Do We Measure It?
* **Matter**: Anything that has mass and takes up volume.
* **Mass vs. Weight**: Mass is measured in grams using a **pan balance**. Weight is the force of gravity measured with a **spring scale**.
* **Volume**: The space occupied by matter (measured in mL using a graduated cylinder or $\text{cm}^3$ using a ruler).
* **States of Matter**:
  * **Solid**: Rigid, fixed vibrating particles; definite shape and volume.
  * **Liquid**: Particles remain in contact but slide past one another; definite volume, takes the container's shape.
  * **Gas**: High-energy particles spread far apart to fill any container; has real mass.
* **Density**: $\text{Density} = \frac{\text{Mass}}{\text{Volume}}$. Pure water is $1.0\text{ g/mL}$. Substances with density $> 1.0$ sink; $< 1.0$ float.
* **Conductivity & Magnetism**: Conductors (copper, iron, aluminum) easily transfer electricity or thermal energy. Insulators (rubber, plastic, wood) resist transfer. Only iron, nickel, and cobalt are magnetic.
""",
        "example": """
* **Density Tower Layering**:
  * Rubbing Alcohol ($0.79\text{ g/mL}$) floats on top.
  * Fresh Water ($1.00\text{ g/mL}$) sits in the middle.
  * Corn Syrup ($1.38\text{ g/mL}$) sinks to the bottom.
""",
        "trap": "Don't assume all metals are magnetic! Copper, aluminum, gold, and brass do NOT stick to magnets.",
    },
    "Changes in Matter": {
        "title": "Physical vs. Chemical Changes & Conservation of Mass",
        "concept": """
### 👩‍🏫 Unit 2: Changes in Matter
* **Physical Change**: Changes shape, size, or state of matter without creating a new chemical substance (e.g., melting ice, dissolving sugar, tearing paper). These are generally reversible.
* **Chemical Change**: Reactants rearrange chemically into brand-new substances with new properties (e.g., rusting, baking, burning, vinegar + baking soda).
* **Signs of a Chemical Reaction**:
  1. Spontaneous gas bubble formation without boiling.
  2. Precipitate formation (insoluble solid appearing from two clear liquids).
  3. Unexpected color shift.
  4. Temperature changes without external heat (exothermic releases heat; endothermic absorbs heat).
* **Law of Conservation of Mass**: Matter is never created or destroyed. In closed systems, initial mass equals final mass.
""",
        "example": """
* **Conservation in a Sealed Flask**:
  * Empty flask & balloon: $60\text{ g}$
  * Vinegar: $75\text{ g}$
  * Baking soda: $15\text{ g}$
  * Total mass before reaction $= 60 + 75 + 15 = 150\text{ g}$.
  * Total mass after reaction (sealed) $= \mathbf{150\text{ g}}$.
""",
        "trap": "In an open container, gas produced escapes into the surrounding air. The mass appears to decrease on the scale, but the atoms were not destroyed!",
    },
    "Earth's Systems": {
        "title": "Earth's Four Interacting Spheres",
        "concept": """
### 👩‍🏫 Earth's Spheres
* **Geosphere**: Solid rock, minerals, soil, mountains, and continental crust.
* **Hydrosphere**: All liquid and frozen water (oceans, lakes, rivers, groundwater).
* **Atmosphere**: Blanket of air and weather gases surrounding the planet.
* **Biosphere**: All living organisms (plants, animals, fungi, bacteria).
""",
        "example": "A rushing river (Hydrosphere) slowly carves a deep rock canyon (Geosphere).",
        "trap": "Clouds are liquid water droplets or ice crystals suspended in air—they belong to the Hydrosphere interacting with the Atmosphere.",
    },
    "Earth's Water": {
        "title": "Earth's Global Water Distribution",
        "concept": """
### 👩‍🏫 Water Reservoir Breakdown
* **97% Saltwater**: Found in oceans and seas.
* **3% Freshwater**:
  * **~68–69%** locked up in solid glaciers and polar ice caps.
  * **~30%** stored in underground aquifers.
  * **Less than 1%** accessible surface water in lakes, rivers, and the atmosphere.
""",
        "example": "Over two-thirds of all freshwater on Earth is unavailable as drinking water because it is frozen in ice caps.",
        "trap": "Rivers and lakes make up less than 1% of total freshwater, not the majority!",
    },
    "Patterns in Space": {
        "title": "Earth Cycles, Sun Angles, and Star Brightness",
        "concept": """
### 👩‍🏫 Celestial Patterns
* **Earth's Rotation (24 hours)**: Causes day and night and the apparent motion of the Sun. Lower Sun angles in early morning/late afternoon cast long shadows; midday Sun casts the shortest shadows.
* **Earth's Revolution (365.25 days)**: Causes different constellations to appear during different seasons.
* **Apparent Star Brightness**: A star's brightness to observers on Earth depends on both its actual energy output and its distance from Earth.
""",
        "example": "A nearby dim star can appear brighter in our night sky than a distant supergiant star.",
        "trap": "Shadows do not change size because the Sun gets closer; they change because Earth's rotation alters the angle of incoming sunlight.",
    },
    "Matter & Energy in Ecosystems": {
        "title": "Energy Flow & Nutrient Cycling",
        "concept": """
### 👩‍🏫 Living Systems
* **Producers**: Plants capture solar energy and use carbon dioxide and water to produce glucose during photosynthesis.
* **Consumers**: Animals that eat plants or other animals for energy.
* **Decomposers**: Fungi and bacteria that break down dead matter, returning nutrients to the soil.
* **Plant Mass Source**: Trees gain their dry mass from carbon dioxide gas absorbed from the air, not from consuming soil.
""",
        "example": "Sunlight $\\rightarrow$ Kelp (Producer) $\\rightarrow$ Sea Urchin (Consumer) $\\rightarrow$ Sea Otter (Apex Predator).",
        "trap": "Soil provides minerals and water, but the structural carbon atoms making up plant wood come from the air!",
    },
}

# ==============================================================================
# 3. 2D & 3D IN-MEMORY DIAGRAM GENERATORS
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
            edgecolor="#222",
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
            edgecolor="#222",
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
                edgecolor="#222",
                lw=1.5,
            )
        )
    ax.add_patch(
        patches.Ellipse(
            (x_offset + cyl_w / 2, 0.2 + cyl_h),
            cyl_w,
            0.25,
            facecolor="none",
            edgecolor="#222",
            lw=2,
        )
    )
    for i in range(1, 6):
        y = 0.2 + (cyl_h - 0.5) * (i / 5.0)
        ax.plot([x_offset, x_offset + 0.35], [y, y], color="#222", lw=1.5)
        ax.text(
            offset := x_offset + 0.45,
            y - 0.1,
            f"{int((max_vol / 5) * i)}",
            fontsize=8,
            weight="bold",
        )
    ax.text(
        x_offset + cyl_w / 2,
        -0.7,
        label,
        ha="center",
        weight="bold",
        fontsize=14,
    )


def generate_diagram(diagram_type: str, params: dict) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6.5, 3.8), dpi=130)

    if diagram_type == "graduated_cylinders":
        render_cylinder(ax, 1.5, params["vol_a"], params["max_vol"], params["label_a"])
        render_cylinder(ax, 5.2, params["vol_b"], params["max_vol"], params["label_b"])
        ax.set(xlim=(0, 8.5), ylim=(-1.2, 6.5))

    elif diagram_type == "density_column":
        ax.add_patch(
            patches.Rectangle((2.5, 0.5), 3.0, 5.0, facecolor="none", edgecolor="#222", lw=3)
        )
        colors = ["#f39c12", "#3498db", "#27ae60"]
        labels = params.get(
            "layers", ["Top (0.8 g/mL)", "Middle (1.0 g/mL)", "Bottom (1.3 g/mL)"]
        )
        for i in range(3):
            ax.add_patch(
                patches.Rectangle(
                    (2.5, 0.5 + i * 1.6),
                    3.0,
                    1.6,
                    facecolor=colors[i],
                    alpha=0.6,
                    edgecolor="#333",
                )
            )
            ax.text(
                4.0,
                1.3 + i * 1.6,
                labels[i],
                ha="center",
                weight="bold",
                fontsize=11,
            )
        ax.set(xlim=(1, 8), ylim=(0, 6.5))

    elif diagram_type == "flask_balloon":
        ax.add_patch(
            patches.Polygon(
                [[3.5, 0.5], [6.5, 0.5], [5.5, 3.2], [5.5, 4.0], [4.5, 4.0], [4.5, 3.2]],
                closed=True,
                facecolor="#eef2f7",
                edgecolor="#222",
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
            ax.add_patch(
                patches.Ellipse(
                    (5.0, 5.0),
                    width=2.4,
                    height=2.2,
                    facecolor="#ff6b6b",
                    edgecolor="#c92a2a",
                    lw=2,
                )
            )
            ax.text(
                5.0,
                5.0,
                "Gas Trapped",
                ha="center",
                va="center",
                color="white",
                weight="bold",
            )
        else:
            ax.add_patch(
                patches.Ellipse(
                    (5.0, 4.3),
                    width=0.8,
                    height=0.6,
                    facecolor="#ff6b6b",
                    edgecolor="#c92a2a",
                    lw=2,
                )
            )
        ax.text(
            5.0,
            -0.2,
            f"Total Mass = {params['total_mass']} g",
            ha="center",
            weight="bold",
            fontsize=12,
        )
        ax.set(xlim=(1, 9), ylim=(-0.8, 6.5))

    elif diagram_type == "pan_balance":
        ax.plot([2, 8], [2.5, 2.5], color="#333", lw=4)
        ax.add_patch(
            patches.Polygon(
                [[4.5, 0.5], [5.5, 0.5], [5.0, 2.5]],
                closed=True,
                facecolor="#7f8c8d",
            )
        )
        ax.plot([3, 3], [1.5, 2.5], color="#555", lw=2)
        ax.plot([2.2, 3.8], [1.5, 1.5], color="#222", lw=3)
        ax.text(3, 1.8, params.get("left_label", "Object A"), ha="center", weight="bold")
        ax.plot([7, 7], [1.5, 2.5], color="#555", lw=2)
        ax.plot([6.2, 7.8], [1.5, 1.5], color="#222", lw=3)
        ax.text(7, 1.8, params.get("right_label", "Object B"), ha="center", weight="bold")
        ax.set(xlim=(1, 9), ylim=(0, 3.5))

    elif diagram_type == "shadow_diagram":
        sun_x, sun_y = params["sun_x"], params["sun_y"]
        pole_x, pole_h = 5.0, 3.5
        ax.plot([0, 10], [0, 0], color="#333", lw=3)
        ax.plot([pole_x, pole_x], [0, pole_h], color="#444", lw=4)
        ax.text(pole_x, -0.4, "Flagpole", ha="center", weight="bold", fontsize=10)
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
            fontsize=10,
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
# 4. UNIT 1: PROPERTIES OF MATTER GENERATORS
# ==============================================================================
def u1_measuring_tools():
    tools = [
        (
            "pan balance",
            "mass in grams",
            "graduated cylinder",
            "liquid volume in milliliters",
        ),
        (
            "graduated cylinder",
            "volume in milliliters",
            "spring scale",
            "weight in newtons",
        ),
        (
            "metric ruler",
            "solid volume in cubic centimeters",
            "thermometer",
            "temperature in degrees Celsius",
        ),
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


def u1_thermal_conductivity():
    materials = [
        (
            "wooden spoon",
            "thermal insulator",
            "wood does not easily permit thermal energy to travel through it",
        ),
        (
            "metal spoon",
            "thermal conductor",
            "metals allow thermal energy to transfer through them very quickly",
        ),
        (
            "silicone spatula",
            "thermal insulator",
            "silicone resists the flow of heat energy and keeps the handle cool",
        ),
    ]
    name, role, reason = random.choice(materials)
    soup_temp = random.randint(75, 90)
    correct = f"{name.capitalize()} is a {role}, because {reason}."
    other_role = (
        "thermal conductor" if role == "thermal insulator" else "thermal insulator"
    )
    distractors = [
        f"{name.capitalize()} is a {other_role}, because it easily dissolves into warm liquids over time.",
        f"{name.capitalize()} is a magnetic material, which completely blocks heat from entering the handle.",
        f"{name.capitalize()} is a {role}, because it immediately transforms into a gas when heated.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_thermal_cond",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student leaves a {name} resting inside a pot of hot vegetable soup at {soup_temp}°C for 15 minutes.",
        "question": f"When touching the handle, which statement correctly explains how thermal energy behaves in the {name}?",
        "hint": "Does heat flow easily through this material to make it hot (conductor), or does it resist heat (insulator)?",
        "answer": ans,
        "explanation": f"{name.capitalize()} is classified as a {role} because {reason}.",
    }


def u1_density_sink_float():
    obj = random.choice([
        (
            "solid oak wood block",
            0.75,
            "floats near the water surface",
            "its density is less than 1.0 g/mL",
        ),
        (
            "pure lead sinker",
            11.34,
            "sinks rapidly to the bottom",
            "its density is much greater than 1.0 g/mL",
        ),
        (
            "paraffin wax cube",
            0.90,
            "floats mostly submerged",
            "its density is slightly less than 1.0 g/mL",
        ),
        (
            "glass marble",
            2.50,
            "sinks directly to the bottom",
            "its density is greater than 1.0 g/mL",
        ),
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


def u1_particle_state_spacing():
    states = [
        (
            "solid ice cube",
            "packed tightly in fixed, vibrating positions with a definite shape and volume",
        ),
        (
            "liquid water",
            "in close contact but able to slide freely past one another, taking the shape of the container",
        ),
        (
            "water vapor gas",
            "spaced very far apart and moving rapidly in all directions to fill any container",
        ),
    ]
    pick = random.choice(states)
    name, desc = pick
    other1 = states[(states.index(pick) + 1) % 3][1]
    other2 = states[(states.index(pick) + 2) % 3][1]
    correct = f"Particles are {desc}."
    distractors = [
        f"Particles are {other1}.",
        f"Particles are {other2}.",
        "Particles have broken down completely into individual protons and ceased movement.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_particles",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student views a microscopic animation of molecules in a sample of {name}.",
        "question": f"Which statement accurately describes the arrangement and motion of the particles in the {name}?",
        "hint": "Solids vibrate in fixed spots, liquids slide around each other, and gases fly far apart.",
        "answer": ans,
        "explanation": f"In a {name}, particles are {desc}.",
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


def u1_electrical_conductors_insulators():
    setups = [
        ("copper wire", "lightbulb glows brightly", "electrical conductor"),
        ("rubber eraser", "lightbulb stays dark", "electrical insulator"),
    ]
    item, bulb, cat = random.choice(setups)
    correct = f"The {item} is an {cat} because it {'allows electric current to flow through the circuit' if 'conductor' in cat else 'blocks electric current from flowing'}."
    other_cat = (
        "electrical insulator" if "conductor" in cat else "electrical conductor"
    )
    distractors = [
        f"The {item} is an {other_cat} because it completely reverses the voltage of the battery.",
        f"The {item} dissolved in the electric wires and permanently altered the battery terminals.",
        "All solid materials allow electric current to pass through them with equal efficiency.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_elec_cond",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student tests a {item} in an electric circuit with a battery and bulb. The {bulb}.",
        "question": f"How should the student classify the {item}?",
        "hint": "Did the bulb turn on? If yes, electricity flows through it (conductor). If not, it blocks it (insulator).",
        "answer": ans,
        "explanation": "Materials that allow current to flow are conductors; materials that block current are insulators.",
    }


def u1_identifying_unknown_substance():
    table = {
        "Property": ["Color / State", "Hardness", "Solubility in Water", "Magnetism"],
        "Result": ["White solid crystals", "Soft", "Dissolves completely", "Not attracted"],
    }
    correct = "Table salt or sugar, because both are soluble, non-magnetic white crystalline solids."
    distractors = [
        "Iron filings, because iron dissolves rapidly in water and forms clear liquid solutions.",
        "Chalk powder, because chalk crystals dissolve completely in room-temperature water.",
        "Copper wire clippings, because copper is a white crystalline solid that dissolves in water.",
    ]
    opts, ans = helper_shuffle_options(correct, distractors)
    return {
        "template_id": "u1_unknown_sub",
        "topic": "Properties of Matter",
        "input_type": "radio",
        "options": opts,
        "table": table,
        "scenario": "A student records physical property tests for an unknown white powder found in the lab.",
        "question": "Which substance could this mystery sample be based on the recorded data?",
        "hint": "Which choice is white, crystalline, and dissolves in water without sticking to a magnet?",
        "answer": ans,
        "explanation": "Table salt and sugar match all observed properties: white crystals, soluble in water, non-magnetic.",
    }


# ==============================================================================
# 5. UNIT 2: CHANGES IN MATTER GENERATORS (VERIFIED ARITHMETIC)
# ==============================================================================
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


def u2_conservation_melting():
    ice_g = random.randint(40, 80)
    flask_g = random.randint(90, 120)
    total = ice_g + flask_g

    opts, ans = helper_shuffle_options(
        f"Exactly {total} grams, because changing states of matter does not alter the amount of matter.",
        [
            f"{total - 10} grams, because liquid water is denser than ice and therefore loses weight on scales.",
            f"{total + 15} grams, because thermal energy absorbed from sunlight adds measurable mass to liquids.",
            f"{flask_g} grams, because all the solid ice molecules were destroyed during phase transition.",
        ],
    )
    return {
        "template_id": "u2_melting",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": (
            f"A student places {ice_g} g of ice inside an empty glass flask ({flask_g} g) and inserts a rubber stopper. "
            f"The digital scale displays a starting mass of {total} g ({flask_g}g flask + {ice_g}g ice). "
            f"She leaves the flask in the sun until all the ice melts completely into liquid water."
        ),
        "question": "What will the scale read after the ice has melted inside the sealed flask?",
        "hint": f"The flask remained sealed! Add {flask_g} g (flask) + {ice_g} g (melted water). Does phase change destroy mass?",
        "answer": ans,
        "explanation": f"Melting is a physical state change in a closed system. Mass remains identical at {total} g ({flask_g}g + {ice_g}g).",
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


def u2_open_beaker_gas_loss():
    liq = random.randint(150, 220)
    tab = random.choice([4, 5, 6])
    loss = random.choice([2, 3])
    initial = liq + tab
    final = initial - loss

    opts, ans = helper_shuffle_options(
        f"{loss} grams of carbon dioxide gas escaped into the room air because the beaker was open.",
        [
            "The antacid tablet was completely destroyed by water, eliminating its atoms from existence.",
            "Liquid water evaporated instantly due to boiling heat generated by the tablet.",
            "The digital scale lost calibration because vigorous gas bubbles vibrated the platform.",
        ],
    )
    return {
        "template_id": "u2_open_beaker",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": (
            f"A student places an open beaker containing {liq} g of water on a balance and sets a {tab} g antacid "
            f"tablet beside it. The scale shows a combined starting mass of {initial} g ({liq}g + {tab}g). "
            f"She drops the tablet into the water. Bubbles fizz vigorously as gas forms. "
            f"Once bubbling completely stops, the balance reads {final} g."
        ),
        "question": f"Why does the final reading show {loss} g less mass than the {initial} g starting mass?",
        "hint": f"Subtract: {initial} g - {final} g = {loss} g. The container was open—where did the gas go?",
        "answer": ans,
        "explanation": f"In an open system, the gas escapes into the room. The {loss} g lost ({initial}g - {final}g) is the mass of the escaped gas.",
    }


def u2_rusting_mass_gain():
    pad = 20
    gain = 2.5
    table = {
        "Stage": ["Day 1: Clean Dry Steel Wool", "Day 4: Rusted Steel Wool"],
        "Observation": ["Shiny, flexible metallic fibers", "Reddish-brown, crumbly crust"],
        "Mass on Balance": [f"{pad}.0 g", f"{pad + gain} g"],
    }
    opts, ans = helper_shuffle_options(
        "Iron atoms chemically bonded with oxygen atoms from the air to form rust, adding mass.",
        [
            "The digital scale malfunctioned, because chemical changes are proven to always reduce mass.",
            "Water moisture from the air soaked into the iron fibers and permanently turned into solid metal.",
            "Matter was created out of nothing by the humid atmosphere surrounding the steel wool pad.",
        ],
    )
    return {
        "template_id": "u2_rusting",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "table": table,
        "scenario": f"A student dampens clean steel wool ({pad}.0 g) and leaves it on a balance exposed to air for 4 days.",
        "question": f"Why does the rusted steel wool weigh {gain} g MORE than the original steel wool?",
        "hint": "Rust is iron oxide. Iron bonded with oxygen atoms taken from the air. What did that add to the solid?",
        "answer": ans,
        "explanation": "Iron combines chemically with oxygen from the air. The added mass comes from the bonded oxygen atoms.",
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


def u2_temperature_change_rxn():
    opts, ans = helper_shuffle_options(
        "A chemical change that released heat energy (an exothermic reaction).",
        [
            "A physical change where water molecules were boiled away into invisible steam.",
            "A chemical change that absorbed heat energy from the air (an endothermic reaction).",
            "A measurement error caused by glass expanding against the thermometer bulb.",
        ],
    )
    return {
        "template_id": "u2_temp_rxn",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": "A student dissolves white pellets into room-temperature water (21°C). Without heating from outside, the temperature rises to 44°C.",
        "question": "What type of change occurred in the beaker?",
        "hint": "The water got hot all by itself! Releasing heat energy indicates an exothermic chemical change.",
        "answer": ans,
        "explanation": "Releasing thermal energy (getting hotter without external heating) is a clear sign of an exothermic chemical change.",
    }


def u2_reversibility_classification():
    examples = [
        (
            "Melting an ice pop in a glass bowl",
            "Physical change",
            "easily reversible by placing the liquid back into a freezer",
        ),
        (
            "Toasting a slice of white bread in a toaster",
            "Chemical change",
            "irreversible because heat created brand-new chemical compounds",
        ),
        (
            "Dissolving lemonade powder into cold water",
            "Physical change",
            "reversible by boiling away the liquid water to recover the solid powder",
        ),
        (
            "Burning a wooden matchstick",
            "Chemical change",
            "irreversible because wood reacted into smoke, ash, and gases",
        ),
    ]
    item, kind, rev = random.choice(examples)
    wrong_kind = "Chemical change" if kind == "Physical change" else "Physical change"
    opts, ans = helper_shuffle_options(
        f"{kind}, and it is {rev}.",
        [
            f"{wrong_kind}, and it is permanently irreversible under any conditions.",
            f"{kind}, but all the mass in the original substance was destroyed.",
            f"{wrong_kind}, because the substance changed temperature during the process.",
        ],
    )
    return {
        "template_id": "u2_reversibility",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student investigates whether everyday changes can be undone: **{item}**.",
        "question": "How is this process classified, and is it reversible?",
        "hint": "Can you freeze melted juice back into an ice pop? Can you un-toast bread?",
        "answer": ans,
        "explanation": f"{item} is a {kind} because it is {rev}.",
    }


def u2_factors_affecting_rate():
    factors = [
        (
            "Crushed powdered sugar vs. a whole sugar cube of equal mass in 20°C water",
            "The powder dissolves faster because smaller particles have more surface area touching water.",
        ),
        (
            "Dropping an antacid tablet in 10°C water vs. 60°C water",
            "The tablet in 60°C water reacts faster because hot molecules move faster and collide more often.",
        ),
        (
            "Two cups of salt water: Cup A is stirred vigorously while Cup B sits still",
            "Cup A dissolves faster because stirring circulates fresh water molecules around the salt.",
        ),
    ]
    setup, correct_reason = random.choice(factors)
    opts, ans = helper_shuffle_options(
        correct_reason,
        [
            "Both will dissolve at the exact same rate because mass is always conserved in reactions.",
            "The colder, un-stirred sample will dissolve faster because cold prevents liquid decay.",
            "Neither sample will dissolve because solid particles cannot mix with liquid molecules.",
        ],
    )
    return {
        "template_id": "u2_rxn_rate",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student investigates what affects reaction rates: **{setup}**.",
        "question": "What will the student observe, and which scientific explanation is correct?",
        "hint": "Think about heat speeding up molecules, or crushing solids to give more surface area.",
        "answer": ans,
        "explanation": correct_reason,
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


def u2_candle_dual_change():
    opts, ans = helper_shuffle_options(
        "Wax melting is a physical change (state change), while wick and wax vapor burning is a chemical change.",
        [
            "Both wax melting and the burning flame are classified as purely physical changes.",
            "Both wax melting and the burning flame are chemical changes that permanently destroy atoms.",
            "The burning flame is a physical change because light and thermal heat have measurable mass.",
        ],
    )
    return {
        "template_id": "u2_candle",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": "A student watches a burning candle. Solid wax melts into a clear liquid pool, while the wick burns and produces smoke.",
        "question": "Which statement correctly distinguishes between the two processes occurring simultaneously?",
        "hint": "Melting turns solid wax to liquid wax (can freeze back). Burning creates smoke and ash (cannot un-burn).",
        "answer": ans,
        "explanation": "Melting wax is a reversible physical change of state. Burning is a chemical change producing smoke and gases.",
    }


def u2_water_cycle_phase_changes():
    changes = [
        (
            "Water vapor in the air cools and forms water droplets on a cold glass",
            "Condensation",
            "gas to liquid",
        ),
        (
            "A shallow puddle of rainwater on a hot asphalt driveway disappears by noon",
            "Evaporation",
            "liquid to gas",
        ),
        (
            "Liquid water inside ice cube trays placed in a freezer becomes solid ice",
            "Freezing",
            "liquid to solid",
        ),
    ]
    scenario, term, trans = random.choice(changes)
    wrong_term = "Condensation" if term == "Evaporation" else "Evaporation"
    opts, ans = helper_shuffle_options(
        f"{term}, which is a physical change from {trans}.",
        [
            f"{wrong_term}, which is a chemical change producing brand-new molecules.",
            f"{term}, which is a chemical reaction that completely destroys water mass.",
            "A permanent transformation that cannot be reversed by heating or cooling.",
        ],
    )
    return {
        "template_id": "u2_phase",
        "topic": "Changes in Matter",
        "input_type": "radio",
        "options": opts,
        "scenario": f"A student observes: **{scenario}**.",
        "question": f"What scientific process occurred, and how is it classified?",
        "hint": "Is water still water when it turns into vapor or droplets? Yes! So it's a physical state change.",
        "answer": ans,
        "explanation": f"{scenario} is {term} ({trans}), which is a physical change.",
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
# 7. MASTER GENERATOR REGISTRY
# ==============================================================================
GENERATORS = [
    # Unit 1: Properties of Matter (12 Dedicated Functions)
    u1_measuring_tools,
    u1_thermal_conductivity,
    u1_density_sink_float,
    u1_density_column_visual,
    u1_magnetism_metals,
    u1_solubility_saturation,
    u1_particle_state_spacing,
    u1_gas_has_mass,
    u1_graduated_cylinder_volume,
    u1_pan_balance_comparison,
    u1_electrical_conductors_insulators,
    u1_identifying_unknown_substance,
    # Unit 2: Changes in Matter (12 Dedicated Functions)
    u2_conservation_dissolving,
    u2_conservation_melting,
    u2_closed_balloon_gas,
    u2_open_beaker_gas_loss,
    u2_rusting_mass_gain,
    u2_precipitate_indicator,
    u2_temperature_change_rxn,
    u2_reversibility_classification,
    u2_factors_affecting_rate,
    u2_multistep_mixture_separation,
    u2_candle_dual_change,
    u2_water_cycle_phase_changes,
    # Other Curriculum Topics
    gen_patterns_in_space_factory,
    gen_earths_systems_factory,
    gen_earths_water_factory,
    gen_ecosystems_factory,
]

TOPIC_TO_GENERATORS = {}
for g in GENERATORS:
    dummy = g()
    TOPIC_TO_GENERATORS.setdefault(dummy["topic"], []).append(g)

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
                if st.session_state.student
                and st.session_state.student["name"] in names
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
    unit1_and_2 = [
        t for t in ["Properties of Matter", "Changes in Matter"] if t in ALL_TOPICS
    ]
    selected_topics = st.multiselect(
        "🎯 Focus Units for Today:",
        ALL_TOPICS,
        default=unit1_and_2 if unit1_and_2 else [ALL_TOPICS[0]],
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
    st.image(img_buffer, width=460)

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

    elif input_mode == "multi_text":
        user_response = {}
        for field in q["blank_fields"]:
            user_response[field["key"]] = st.text_input(
                field["label"],
                placeholder=field["placeholder"],
                disabled=st.session_state.answered,
                key=f"field_{field['key']}_{st.session_state.q_counter}",
            )

    else:
        user_response = st.text_input(
            "Fill in the blank:",
            placeholder=q.get("placeholder", "Type your answer here..."),
            disabled=st.session_state.answered,
        )

    submit = st.form_submit_button(
        "Check Answer", disabled=st.session_state.answered
    )

    if submit and not st.session_state.answered:
        has_input = False
        if input_mode == "multiselect":
            has_input = len(user_response) > 0
        elif input_mode == "multi_text":
            has_input = all(str(v).strip() != "" for v in user_response.values())
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
            elif input_mode == "multi_text":
                correct_ans_display = " | ".join(
                    [f"{k}: {v[0]}" for k, v in q.get("accepted_answers_dict", {}).items()]
                )

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

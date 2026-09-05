# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "streamlit",
#     "pandas",
#     "matplotlib",
# ]
# ///

import io
import random
import sqlite3
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# ==============================================================================
# 1. DATABASE SETUP & PERSISTENCE
# ==============================================================================
DB_FILE = "science_tutor.db"


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS topic_mastery (
                student_id INTEGER,
                topic TEXT,
                mastery REAL DEFAULT 0.0,
                PRIMARY KEY (student_id, topic),
                FOREIGN KEY (student_id) REFERENCES students (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attempt_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                topic TEXT,
                template_id TEXT,
                is_correct INTEGER,
                selected_answer TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students (id)
            )
        """)
        cursor.execute("PRAGMA table_info(attempt_logs)")
        if "template_id" not in [row["name"] for row in cursor.fetchall()]:
            cursor.execute("ALTER TABLE attempt_logs ADD COLUMN template_id TEXT")
        conn.commit()


def list_students():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM students ORDER BY name ASC")
        return [dict(row) for row in cursor.fetchall()]


def get_or_create_student(name: str):
    clean_name = name.strip().capitalize()
    if not clean_name: return None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM students WHERE name = ?", (clean_name,))
        row = cursor.fetchone()
        if row: return dict(row)
        cursor.execute("INSERT INTO students (name) VALUES (?)", (clean_name,))
        conn.commit()
        return {"id": cursor.lastrowid, "name": clean_name}


def load_mastery(student_id: int, all_topics: list[str]) -> dict[str, float]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT topic, mastery FROM topic_mastery WHERE student_id = ?", (student_id,))
        mastery = {row["topic"]: row["mastery"] for row in cursor.fetchall()}
        for topic in all_topics:
            if topic not in mastery:
                mastery[topic] = 0.0
                cursor.execute("INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (?, ?, 0.0)",
                               (student_id, topic))
        conn.commit()
        return mastery


def reset_student_progress(student_id: int, all_topics: list[str]):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM attempt_logs WHERE student_id = ?", (student_id,))
        for topic in all_topics:
            cursor.execute("""
                INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (?, ?, 0.0)
                ON CONFLICT(student_id, topic) DO UPDATE SET mastery = 0.0
            """, (student_id, topic))
        conn.commit()


def record_attempt(student_id: int, topic: str, template_id: str, is_correct: bool, selected_answer: str,
                   new_mastery: float):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO attempt_logs (student_id, topic, template_id, is_correct, selected_answer)
            VALUES (?, ?, ?, ?, ?)
        """, (student_id, topic, template_id, 1 if is_correct else 0, selected_answer))
        cursor.execute("""
            INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (?, ?, ?)
            ON CONFLICT(student_id, topic) DO UPDATE SET mastery = excluded.mastery
        """, (student_id, topic, new_mastery))
        conn.commit()


# ==============================================================================
# 2. IN-MEMORY VISUAL DIAGRAM GENERATORS
# ==============================================================================
def render_cylinder(ax, x_offset, volume, max_vol, label, fill_color="#7b8d9e"):
    cyl_w, cyl_h, fill_pct = 1.6, 5.5, volume / max_vol
    ax.add_patch(patches.Ellipse((x_offset + cyl_w / 2, 0.2), width=cyl_w + 1.1, height=0.45, facecolor="#e0e0e0",
                                 edgecolor="#222", lw=2))
    liquid_height = (cyl_h - 0.5) * fill_pct
    ax.add_patch(patches.Rectangle((x_offset, 0.2), cyl_w, liquid_height, facecolor=fill_color, edgecolor="none"))
    ax.add_patch(patches.Rectangle((x_offset, 0.2), cyl_w, cyl_h, facecolor="none", edgecolor="#222", lw=2.5))
    if fill_pct > 0:
        ax.add_patch(
            patches.Ellipse((x_offset + cyl_w / 2, 0.2 + liquid_height), width=cyl_w, height=0.25, facecolor="#5f7182",
                            edgecolor="#222", lw=1.5))
    ax.add_patch(patches.Ellipse((x_offset + cyl_w / 2, 0.2 + cyl_h), width=cyl_w, height=0.25, facecolor="none",
                                 edgecolor="#222", lw=2))
    for i in range(1, 6):
        tick_y = 0.2 + (cyl_h - 0.5) * (i / 5.0)
        ax.plot([x_offset, x_offset + 0.35], [tick_y, tick_y], color="#222", lw=1.5)
        ax.text(x_offset + 0.45, tick_y - 0.1, f"{int((max_vol / 5) * i)}", fontsize=8, weight="bold", color="#333")
    ax.text(x_offset + cyl_w / 2, -0.7, label, ha="center", va="center", fontsize=16, weight="bold")


def generate_diagram(diagram_type: str, params: dict) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6.5, 3.8), dpi=130)
    if diagram_type == "graduated_cylinders":
        render_cylinder(ax, 1.5, params["vol_a"], params["max_vol"], f"Sample {params['label_a']}")
        render_cylinder(ax, 5.2, params["vol_b"], params["max_vol"], f"Sample {params['label_b']}")
        ax.set(xlim=(0, 8.5), ylim=(-1.2, 6.5))
    elif diagram_type == "flask_balloon":
        ax.add_patch(
            patches.Polygon([[3.5, 0.5], [6.5, 0.5], [5.5, 3.2], [5.5, 4.0], [4.5, 4.0], [4.5, 3.2]], closed=True,
                            facecolor="#eef2f7", edgecolor="#222", lw=2.5))
        ax.add_patch(
            patches.Polygon([[3.8, 0.5], [6.2, 0.5], [5.8, 1.8], [4.2, 1.8]], closed=True, facecolor="#a0c4ff"))
        if params.get("expanded", True):
            ax.add_patch(
                patches.Ellipse((5.0, 5.0), width=2.4, height=2.2, facecolor="#ff6b6b", edgecolor="#c92a2a", lw=2))
            ax.text(5.0, 5.0, "Gas", ha="center", va="center", color="white", weight="bold")
        else:
            ax.add_patch(
                patches.Ellipse((5.0, 4.3), width=0.8, height=0.6, facecolor="#ff6b6b", edgecolor="#c92a2a", lw=2))
        ax.text(5.0, -0.2, f"Total Mass = {params['total_mass']} g", ha="center", weight="bold", fontsize=12)
        ax.set(xlim=(1, 9), ylim=(-0.8, 6.5))
    elif diagram_type == "shadow_diagram":
        sun_x, sun_y, pole_x, pole_h = params["sun_x"], params["sun_y"], 5.0, 3.5
        ax.plot([0, 10], [0, 0], color="#333", lw=3)
        ax.plot([pole_x, pole_x], [0, pole_h], color="#444", lw=4)
        ax.plot([pole_x, max(0.5, min(9.5, pole_x - (pole_h / ((pole_h - sun_y) / (pole_x - sun_x)))))], [0, 0],
                color="#666", lw=7, solid_capstyle="round")
        ax.scatter([sun_x], [sun_y], color="#f39c12", s=450, zorder=5)
        ax.text(sun_x, sun_y + 0.6, f"Sun ({params['time_label']})", ha="center", weight="bold", fontsize=10)
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
    labeled_opts = [f"{['A', 'B', 'C', 'D'][i]}. {opt}" for i, opt in enumerate(opts)]
    return labeled_opts, labeled_opts[opts.index(correct_text)]


# ==============================================================================
# 3. PROCEDURAL QUESTION GENERATORS
# ==============================================================================

# --- Category A: Changes in Matter (10 Specialized Generators) ---
def gen_closed_balloon_system():
    student, v, b, f = random.choice(["Maya", "Liam", "Ava"]), random.randint(70, 120), random.randint(10,
                                                                                                       25), random.randint(
        60, 95)
    total = v + b + f
    options, ans = helper_shuffle_options(
        f"Exactly {total} grams, because the balloon prevents gas from escaping.",
        [f"Less than {total} grams, because gases produced have no mass.",
         f"Greater than {total} grams, because inflating adds weight.",
         f"{total - b} grams, because solid turned into energy."]
    )
    return {
        "template_id": "closed_balloon", "topic": "Changes in Matter",
        "scenario": f"{student} places {b}g baking soda in a balloon over a flask holding {v}g vinegar. The flask weighs {f}g. Initial scale reads {total}g. She tips the balloon, vigorous bubbling inflates it.",
        "diagram": "flask_balloon", "diagram_params": {"total_mass": total, "expanded": True},
        "question": "What will the scale display after the chemical reaction finishes?",
        "options": options, "answer": ans,
        "explanation": "In a closed system, matter cannot leave. According to the Law of Conservation of Mass, the reading remains exactly identical."
    }


def gen_open_beaker_gas_mass():
    initial, gas = random.randint(150, 250), round(random.uniform(1.2, 3.5), 1)
    options, ans = helper_shuffle_options(
        "Carbon dioxide gas produced by the reaction escaped into the surrounding room.",
        ["Matter was destroyed as the solid tablet dissolved.", "Liquid water evaporated instantly.",
         "The scale lost calibration."]
    )
    return {
        "template_id": "open_beaker", "topic": "Changes in Matter",
        "scenario": f"A student drops a fizzing tablet into an open beaker of water (Initial Mass = {initial} g). When bubbling stops, the final reading is {round(initial - gas, 1)} g.",
        "question": f"Why does the scale read {gas} g less than the initial mass?",
        "options": options, "answer": ans,
        "explanation": "The beaker is an open system. The missing mass was gas that bubbled out into the air."
    }


def gen_reversibility_changes():
    scenarios = [
        {"n": "Melting beeswax", "t": "Physical change", "r": "Easily reversible by cooling"},
        {"n": "Baking a chocolate cake", "t": "Chemical change",
         "r": "Not reversible because permanent chemical bonds formed"},
        {"n": "Burning a dry pine log", "t": "Chemical change",
         "r": "Not reversible because cellulose reacted with oxygen"},
        {"n": "Freezing grape juice", "t": "Physical change", "r": "Easily reversible by warming"}
    ]
    pick = random.choice(scenarios)
    wrong = "Chemical change" if pick["t"] == "Physical change" else "Physical change"
    options, ans = helper_shuffle_options(
        f"It is a {pick['t']}, and it is {pick['r']}.",
        [f"It is a {wrong}, and it cannot ever be reversed.",
         f"It is a {pick['t']}, but matter was permanently destroyed.",
         f"It is a {wrong}, because mass converted into volume."]
    )
    return {
        "template_id": "reversibility", "topic": "Changes in Matter",
        "scenario": f"A student investigates: **{pick['n']}**.",
        "question": "Which statement correctly classifies this change and evaluates its reversibility?",
        "options": options, "answer": ans,
        "explanation": f"{pick['n']} is a {pick['t']}. Physical state changes can usually be reversed, whereas chemical changes form new compounds."
    }


def gen_precipitate_formation():
    options, ans = helper_shuffle_options(
        "A chemical reaction occurred because two liquids reacted to form an insoluble solid (precipitate).",
        ["A physical change occurred because liquids evaporated.", "Matter was created out of nothing.",
         "No change occurred; they merely blended."]
    )
    return {
        "template_id": "precipitate", "topic": "Changes in Matter",
        "scenario": "A student pours clear Epsom salt solution into clear washing soda solution. Instantly, the mixture turns cloudy and a white chalky solid sinks to the bottom.",
        "question": "What scientific conclusion is best supported by the appearance of the solid?",
        "options": options, "answer": ans,
        "explanation": "Precipitate formation (a solid appearing from two clear liquids) is definitive proof of a chemical change."
    }


def gen_rusting_mass():
    mass = random.randint(15, 25)
    options, ans = helper_shuffle_options(
        "Iron chemically bonded with oxygen atoms from the air, adding mass.",
        ["The digital balance malfunctioned.", "Matter was magically created by humidity.",
         "Water turned into solid metal."]
    )
    return {
        "template_id": "rusting", "topic": "Changes in Matter",
        "scenario": "A student places a damp steel wool pad on a balance. Over 3 days, it rusts, and the mass increases.",
        "table": {"Stage": ["Initial", "Rusted"], "Mass": [f"{mass}.0 g", f"{mass + 2}.4 g"]},
        "question": "Why does the rusted steel wool weigh MORE than the original iron?",
        "options": options, "answer": ans,
        "explanation": "Rust is iron oxide. The added mass comes from oxygen atoms pulled from the surrounding air."
    }


def gen_reaction_rate_variables():
    vars = [
        {"test": "Powdered sugar vs. solid sugar cube in identical water", "fac": "Surface area",
         "res": "Powder dissolves faster because more surface area is exposed to water."},
        {"test": "Antacid tablet in 10°C water vs. 60°C water", "fac": "Temperature",
         "res": "Hot water reacts faster because heated molecules move and collide faster."},
        {"test": "Stirred salt water vs. Unstirred salt water", "fac": "Mechanical agitation",
         "res": "Stirring spreads particles faster."}
    ]
    pick = random.choice(vars)
    options, ans = helper_shuffle_options(pick["res"], ["Both will react at the exact same rate.",
                                                        "The colder/still one reacts faster.",
                                                        "It will never dissolve without acids."])
    return {
        "template_id": "rxn_rate", "topic": "Changes in Matter",
        "scenario": f"A student tests: **{pick['test']}**.",
        "question": f"What will the student observe, and how does {pick['fac']} explain it?",
        "options": options, "answer": ans, "explanation": pick["res"]
    }


def gen_evaporation_conservation():
    water, salt = random.randint(150, 250), random.randint(20, 35)
    options, ans = helper_shuffle_options(
        f"Exactly {salt} grams of white salt crystals will remain.",
        [f"{water + salt} grams of liquid salt.", "0 grams; salt evaporates with water.",
         f"Only {round(salt / 2, 1)} grams because dissolving destroys mass."]
    )
    return {
        "template_id": "evap_conserv", "topic": "Changes in Matter",
        "scenario": f"A student dissolves {salt} g of salt into {water} g of water. She places it under a heat lamp until every drop of water evaporates.",
        "question": "What will be left in the dish, and what will its mass be?",
        "options": options, "answer": ans,
        "explanation": "Dissolving is physical. Water evaporates as gas, but the dissolved solid remains entirely behind."
    }


def gen_multistep_mixture_sep():
    iron, sand, salt = random.randint(15, 30), random.randint(30, 50), random.randint(20, 35)
    options, ans = helper_shuffle_options(
        f"All components are recovered ({iron}g+{sand}g+{salt}g = {iron + sand + salt}g) because physical properties allow separation without destroying matter.",
        ["Mass decreased because filtering destroys particles.", "Salt was destroyed when it turned into liquid.",
         "The magnet altered chemical identities."]
    )
    return {
        "template_id": "multistep_sep", "topic": "Changes in Matter",
        "scenario": f"A {iron + sand + salt}g mixture of iron ({iron}g), sand ({sand}g), and salt ({salt}g) is separated using a magnet, filtering, and boiling.",
        "question": "Which conclusion about the Law of Conservation of Mass is demonstrated here?",
        "options": options, "answer": ans,
        "explanation": "Mixtures are physically combined. Using physical properties allows 100% component recovery."
    }


def gen_candle_dual_change():
    options, ans = helper_shuffle_options(
        "Wax melting is a physical change (state change), while the wick burning is a chemical change.",
        ["Both are purely physical.", "Both are chemical changes that destroy atoms.",
         "The flame is a physical change because light has volume."]
    )
    return {
        "template_id": "candle_dual", "topic": "Changes in Matter",
        "scenario": "A student watches a candle. Solid wax melts into clear liquid pools, while the wick burns black and releases smoke.",
        "question": "Which statement accurately distinguishes between the changes occurring simultaneously?",
        "options": options, "answer": ans,
        "explanation": "Melting is a reversible phase transition (physical). Burning produces new substances like smoke (chemical)."
    }


def gen_thermal_reaction_types():
    options, ans = helper_shuffle_options(
        "A chemical change that released heat energy (exothermic reaction).",
        ["A physical change where water was destroyed.", "A chemical change that absorbed heat (endothermic).",
         "A phase change to plasma."]
    )
    return {
        "template_id": "thermal_rxn", "topic": "Changes in Matter",
        "scenario": "A student dissolves calcium chloride pellets in water. The beaker becomes noticeably hot, rising from 20°C to 42°C.",
        "question": "Based on the temperature readout, which best describes the change?",
        "options": options, "answer": ans,
        "explanation": "Releasing thermal energy (getting hotter) is a clear indicator of an exothermic chemical reaction."
    }


# --- Category B: Multi-Archetype Factories for Other Topics ---

def gen_properties_of_matter_factory():
    archetypes = [
        {
            "id": "density_tower",
            "scenario": "A student pours equal volumes of corn syrup, vegetable oil, and water into a tall glass. They separate into three distinct horizontal layers. The syrup is on the bottom, water in the middle, and oil floating on top.",
            "question": "What physical property causes these liquids to stack in this specific order?",
            "correct": "Density: The syrup has the highest density, and the oil has the lowest.",
            "distractors": ["Solubility: The oil is most soluble.", "Magnetism: The syrup repels the water.",
                            "Temperature: The oil is the hottest liquid."]
        },
        {
            "id": "electrical_conductivity",
            "scenario": "A student tests a circuit with a battery and a lightbulb. When she connects a copper wire, the bulb lights up. When she connects a glass rod, the bulb stays dark.",
            "question": "What physical property is being tested?",
            "correct": "Electrical conductivity",
            "distractors": ["Thermal insulation", "Magnetic attraction", "State of matter"]
        },
        {
            "id": "solubility_temp",
            "scenario": f"A student adds {random.randint(2, 5)} spoons of sugar to a glass of 10°C cold water and another to a glass of 80°C hot water. She stirs both at the same speed.",
            "question": "What will happen to the sugar in the hot water compared to the cold water?",
            "correct": "It will dissolve faster and in greater amounts in the hot water.",
            "distractors": ["It will immediately turn into a gas in the hot water.",
                            "It will dissolve slower in the hot water.", "It will not dissolve in either glass."]
        },
        {
            "id": "cyl_particles",
            "scenario": "A student looks at a particle diagram of a solid block of ice and a liquid glass of water.",
            "question": "How do the particles in the solid ice differ from the liquid water?",
            "correct": "Solid particles are locked in a rigid, vibrating grid, while liquid particles slide past one another.",
            "distractors": ["Solid particles fly freely around the room.", "Liquid particles completely stop moving.",
                            "Solid particles are much larger than liquid particles."]
        },
        {
            "id": "mixture_sep_tool",
            "scenario": "A bowl contains a dry mixture of iron hardware nuts and aluminum screws of the exact same size and color.",
            "question": "Which tool would easily separate this mixture without water?",
            "correct": "A strong magnet, because iron is magnetic and aluminum is not.",
            "distractors": ["A paper filter, because aluminum is smaller.",
                            "A hot plate, because iron melts at room temperature.",
                            "A magnifying glass, to burn the aluminum."]
        }
    ]
    pick = random.choice(archetypes)
    opts, ans = helper_shuffle_options(pick["correct"], pick["distractors"])
    return {"template_id": pick["id"], "topic": "Properties of Matter", "scenario": pick["scenario"],
            "question": pick["question"], "options": opts, "answer": ans,
            "explanation": "Different materials have distinct physical properties (density, conductivity, magnetism, particle arrangement) used to identify and separate them."}


def gen_patterns_in_space_factory():
    archetypes = [
        {
            "id": "constellation_seasons",
            "scenario": "A student easily spots the constellation Orion high in the winter night sky. Six months later, during summer, Orion is completely invisible at night.",
            "question": "What causes Orion to disappear from the summer night sky?",
            "correct": "Earth's yearly revolution (orbit) around the Sun changes which stars are visible at night.",
            "distractors": ["Earth's daily rotation blocks the stars.",
                            "The stars physically fly to the other side of the galaxy.",
                            "The Sun's brightness destroys winter constellations."]
        },
        {
            "id": "day_night_cause",
            "scenario": "It is daytime in New York but nighttime in Tokyo, Japan.",
            "question": "What primary movement in space causes the cycle of day and night?",
            "correct": "Earth rotating on its own axis once every 24 hours.",
            "distractors": ["Earth revolving around the Sun once a year.", "The Sun orbiting around the Earth daily.",
                            "The Moon blocking the Sun's light at night."]
        },
        {
            "id": "star_distance_brightness",
            "scenario": "Star A is a small, dim star located 4 light-years away. Star B is a massive, incredibly bright supergiant located 1,000 light-years away.",
            "question": "Why might Star A appear much brighter to human eyes on Earth than Star B?",
            "correct": "Apparent brightness depends heavily on distance; closer stars appear brighter.",
            "distractors": ["Small stars always generate more energy than supergiants.",
                            "Star B does not emit any visible light.", "Telescopes cannot see past 100 light-years."]
        },
        {
            "id": "shadow_length_time",
            "scenario": f"A student measures a flagpole's shadow at {random.choice(['8:00 AM', '5:00 PM'])}.",
            "question": "Why is the shadow extremely long at this time of day?",
            "correct": "The Sun is at a low angle near the horizon.",
            "distractors": ["The Sun is directly overhead at its highest point.", "The Earth is furthest from the Sun.",
                            "The Moon is creating the shadow."]
        },
        {
            "id": "gravity_scale",
            "scenario": "An astronaut lands on a massive gas giant planet that has 300 times the mass of Earth.",
            "question": "How would the gravitational pull on this planet compare to Earth?",
            "correct": "It would be much stronger because the planet has significantly more mass.",
            "distractors": ["It would be weaker because gas is lighter than rock.",
                            "It would be exactly the same as Earth's gravity.",
                            "Gravity does not exist on other planets."]
        }
    ]
    pick = random.choice(archetypes)
    opts, ans = helper_shuffle_options(pick["correct"], pick["distractors"])
    return {"template_id": pick["id"], "topic": "Patterns in Space", "scenario": pick["scenario"],
            "question": pick["question"], "options": opts, "answer": ans,
            "explanation": "Space patterns (day/night, seasons, apparent brightness, shadows) are driven by Earth's rotation, Earth's orbit, and relative distance."}


def gen_earths_systems_factory():
    archetypes = [
        {
            "id": "sphere_volcano",
            "scenario": "A massive volcano erupts, spewing molten rock and thick clouds of ash blocking sunlight for weeks.",
            "question": "Which two spheres are interacting when the ash blocks the sunlight?",
            "correct": "Geosphere (rock/ash) and Atmosphere (air/sky)",
            "distractors": ["Hydrosphere and Biosphere", "Biosphere and Geosphere", "Hydrosphere and Cryosphere"]
        },
        {
            "id": "sphere_erosion",
            "scenario": "A fast-moving river carves a deep V-shaped canyon into the bedrock over millions of years.",
            "question": "This canyon formation is a direct interaction between the:",
            "correct": "Hydrosphere and Geosphere",
            "distractors": ["Biosphere and Atmosphere", "Atmosphere and Geosphere", "Cryosphere and Biosphere"]
        },
        {
            "id": "sphere_gas_exchange",
            "scenario": "Millions of pine trees in a forest absorb carbon dioxide and release oxygen during photosynthesis.",
            "question": "This gas exchange is an interaction between the:",
            "correct": "Biosphere and Atmosphere",
            "distractors": ["Geosphere and Hydrosphere", "Hydrosphere and Biosphere", "Geosphere and Atmosphere"]
        },
        {
            "id": "sphere_rain_shadow",
            "scenario": "Warm, moist ocean air blows into a tall mountain range, rises, cools, and drops heavy rain on one side of the mountain.",
            "question": "Which spheres are interacting to create this rainfall pattern?",
            "correct": "Atmosphere, Hydrosphere, and Geosphere",
            "distractors": ["Biosphere and Cryosphere only", "Geosphere and Biosphere only",
                            "Atmosphere and Biosphere only"]
        },
        {
            "id": "sphere_roots",
            "scenario": "The roots of an oak tree slowly wedge into a crack in a granite boulder, eventually splitting the rock in half.",
            "question": "Which two spheres are interacting here?",
            "correct": "Biosphere and Geosphere",
            "distractors": ["Hydrosphere and Atmosphere", "Atmosphere and Biosphere", "Hydrosphere and Geosphere"]
        }
    ]
    pick = random.choice(archetypes)
    opts, ans = helper_shuffle_options(pick["correct"], pick["distractors"])
    return {"template_id": pick["id"], "topic": "Earth's Systems", "scenario": pick["scenario"],
            "question": pick["question"], "options": opts, "answer": ans,
            "explanation": "Earth's four major systems (Geosphere=rock, Hydrosphere=water, Atmosphere=air, Biosphere=life) constantly interact to shape the planet."}


def gen_earths_water_factory():
    archetypes = [
        {
            "id": "water_dist_glaciers",
            "scenario": "A student looks at a chart showing all of Earth's freshwater.",
            "question": "Where is the vast majority (nearly 69%) of Earth's freshwater physically located?",
            "correct": "Locked up in solid glaciers and polar ice caps.",
            "distractors": ["Flowing in rivers and streams.", "Floating in the atmosphere as clouds.",
                            "Sitting in the oceans."]
        },
        {
            "id": "water_dist_oceans",
            "scenario": "An astronaut looks at Earth from space and notes it is mostly blue.",
            "question": "Approximately what percentage of ALL water on Earth is saltwater found in oceans?",
            "correct": "About 97%",
            "distractors": ["About 50%", "About 25%", "About 5%"]
        },
        {
            "id": "water_aquifer",
            "scenario": "A farming town gets zero rain for a month, yet they still pump fresh water from a deep well into their fields.",
            "question": "Where is this well water coming from?",
            "correct": "Groundwater stored in underground aquifers (porous rock layers).",
            "distractors": ["Underground saltwater oceans.", "Water magically created by the well pump.",
                            "Condensation directly from the dry air."]
        },
        {
            "id": "water_cycle_evap",
            "scenario": "A puddle of rainwater on a hot sidewalk disappears completely by the afternoon.",
            "question": "What part of the water cycle caused this, and what sphere did the water enter?",
            "correct": "Evaporation; it entered the Atmosphere as a gas.",
            "distractors": ["Precipitation; it entered the Geosphere.", "Condensation; it entered the Biosphere.",
                            "Runoff; it entered the Hydrosphere."]
        }
    ]
    pick = random.choice(archetypes)
    opts, ans = helper_shuffle_options(pick["correct"], pick["distractors"])
    return {"template_id": pick["id"], "topic": "Earth's Water", "scenario": pick["scenario"],
            "question": pick["question"], "options": opts, "answer": ans,
            "explanation": "Most of Earth's water is salty (97%). Of the 3% freshwater, most is frozen in glaciers, leaving very little as surface or groundwater."}


def gen_ecosystems_factory():
    archetypes = [
        {
            "id": "eco_plant_mass",
            "scenario": "A tiny acorn grows into a massive, 2,000-pound oak tree over 50 years.",
            "question": "Where did the vast majority of the matter (mass) making up the wood of the tree come from?",
            "correct": "Carbon dioxide gas absorbed from the air and water.",
            "distractors": ["Solid dirt and soil pulled up by the roots.",
                            "Sunlight magically turning into solid wood.",
                            "Fertilizer crystals scattered on the ground."]
        },
        {
            "id": "eco_decomposers",
            "scenario": "A dead log on the forest floor is covered in mushrooms and bacteria.",
            "question": "What critical role do these organisms (decomposers) play in the ecosystem?",
            "correct": "They break down dead matter and recycle necessary nutrients back into the soil.",
            "distractors": ["They produce oxygen for animals to breathe.",
                            "They hunt small insects to control populations.", "They absorb sunlight to make sugars."]
        },
        {
            "id": "eco_food_web_disruption",
            "scenario": "In a meadow: Grass -> Grasshoppers -> Frogs -> Snakes. A disease wipes out the frog population entirely.",
            "question": "What is the most likely immediate effect on the grasshopper and snake populations?",
            "correct": "Grasshoppers will increase (fewer predators), and snakes will decrease (less food).",
            "distractors": ["Both will increase rapidly.", "Both will decrease rapidly.",
                            "Grasshoppers will decrease, and snakes will increase."]
        },
        {
            "id": "eco_sun_energy",
            "scenario": "Deep ocean kelp (a plant) is eaten by sea urchins, which are eaten by sea otters.",
            "question": "What is the original source of energy that sustains this entire kelp forest food web?",
            "correct": "Sunlight captured by the kelp through photosynthesis.",
            "distractors": ["Heat from deep ocean volcanoes.", "Nutrients produced by the sea otters.",
                            "Salt dissolved in the ocean water."]
        }
    ]
    pick = random.choice(archetypes)
    opts, ans = helper_shuffle_options(pick["correct"], pick["distractors"])
    return {"template_id": pick["id"], "topic": "Matter & Energy in Ecosystems", "scenario": pick["scenario"],
            "question": pick["question"], "options": opts, "answer": ans,
            "explanation": "Ecosystems rely on the Sun for energy, producers to make food (using CO2 and water), consumers to transfer energy, and decomposers to recycle matter."}


# Master Generator Registry
GENERATORS = [
    gen_closed_balloon_system, gen_open_beaker_gas_mass, gen_reversibility_changes,
    gen_precipitate_formation, gen_rusting_mass, gen_reaction_rate_variables,
    gen_evaporation_conservation, gen_multistep_mixture_sep, gen_candle_dual_change,
    gen_thermal_reaction_types,
    gen_properties_of_matter_factory, gen_patterns_in_space_factory,
    gen_earths_systems_factory, gen_earths_water_factory, gen_ecosystems_factory
]

TOPIC_TO_GENERATORS = {}
for g in GENERATORS:
    t = g()["topic"]
    TOPIC_TO_GENERATORS.setdefault(t, []).append(g)

ALL_TOPICS = sorted(list(TOPIC_TO_GENERATORS.keys()))
init_db()

# ==============================================================================
# 4. STREAMLIT APPLICATION UI
# ==============================================================================
st.set_page_config(page_title="Savvas Elevate Science Prep", page_icon="🔬", layout="wide")

for key in ["student", "current_q", "answered", "feedback"]:
    if key not in st.session_state: st.session_state[key] = None
for key in ["mastery", "recent_templates"]:
    if key not in st.session_state: st.session_state[key] = {} if key == "mastery" else []
if "q_counter" not in st.session_state: st.session_state.q_counter = 0

# --- Sidebar UI ---
with st.sidebar:
    st.header("👤 Student Profile")
    existing_students = list_students()
    profile_mode = st.radio("Profile Action:", ["Select Existing Student", "Add New Student"], horizontal=True)

    if profile_mode == "Select Existing Student":
        if existing_students:
            names = [s["name"] for s in existing_students]
            idx = names.index(st.session_state.student["name"]) if st.session_state.student and \
                                                                   st.session_state.student["name"] in names else 0
            chosen_name = st.selectbox("Choose Student:", names, index=idx)
            if st.button("Load Profile"):
                p = get_or_create_student(chosen_name)
                st.session_state.update({"student": p, "mastery": load_mastery(p["id"], ALL_TOPICS), "current_q": None,
                                         "recent_templates": [], "answered": False, "feedback": None})
                st.rerun()
        else:
            st.info("No saved students found. Please choose 'Add New Student'.")
    else:
        new_name = st.text_input("New Student Name:")
        if st.button("Create & Start") and new_name.strip():
            p = get_or_create_student(new_name)
            st.session_state.update(
                {"student": p, "mastery": load_mastery(p["id"], ALL_TOPICS), "current_q": None, "recent_templates": [],
                 "answered": False, "feedback": None})
            st.rerun()

    if st.session_state.student:
        if st.button("🔄 Reset This Student to 0%", type="secondary"):
            reset_student_progress(st.session_state.student["id"], ALL_TOPICS)
            st.session_state.update(
                {"mastery": {t: 0.0 for t in ALL_TOPICS}, "recent_templates": [], "current_q": None, "answered": False,
                 "feedback": None})
            st.toast("Progress reset to 0%!", icon="🔄")
            st.rerun()

    st.markdown("---")
    selected_topics = st.multiselect("🎯 Focus Topics:", ALL_TOPICS, default=[ALL_TOPICS[0]])
    st.markdown("---")

    if st.session_state.student:
        st.header("📊 Topic Mastery")
        for topic in selected_topics:
            score = st.session_state.mastery.get(topic, 0.0)
            st.write(f"**{topic}** ({int(score * 100)}%)")
            st.progress(score)


# --- Question Dispatcher ---
def pick_next_question():
    if not selected_topics: return
    funcs = [f for t in selected_topics for f in TOPIC_TO_GENERATORS.get(t, [])]
    if not funcs: return

    # Anti-repetition: avoid recent archetypes
    cooling = [f for f in funcs if f.__name__ not in st.session_state.recent_templates]
    if not cooling:
        last = st.session_state.recent_templates[-1] if st.session_state.recent_templates else None
        cooling = [f for f in funcs if f.__name__ != last] or funcs
        st.session_state.recent_templates = []

    chosen_func = random.choice(cooling)
    st.session_state.current_q = chosen_func()
    st.session_state.answered = False
    st.session_state.feedback = None
    st.session_state.q_counter += 1

    st.session_state.recent_templates.append(chosen_func.__name__)
    if len(st.session_state.recent_templates) > 6: st.session_state.recent_templates.pop(0)


# --- Main UI Area ---
st.title("🔬 Elevate Science Adaptive Prep")

if not st.session_state.student: st.info("👈 Select or create a student profile to begin."); st.stop()
if not selected_topics: st.warning("👈 Please select at least one unit topic."); st.stop()
if st.session_state.current_q is None or st.session_state.current_q[
    "topic"] not in selected_topics: pick_next_question()

q = st.session_state.current_q
st.caption(f"Unit: **{q['topic']}**")
st.info(f"**Scenario:**\n\n{q['scenario']}")

if "diagram" in q: st.image(generate_diagram(q["diagram"], q.get("diagram_params", {})), width=460)
if "table" in q: st.write("**Reference Data Table:**"); st.dataframe(pd.DataFrame(q["table"]), use_container_width=True,
                                                                     hide_index=True)

st.write(f"### {q['question']}")

with st.form(key=f"form_{q['template_id']}_{st.session_state.q_counter}"):
    user_choice = st.radio("Select your answer:", q["options"], index=None, disabled=st.session_state.answered)
    submit = st.form_submit_button("Submit Answer", disabled=st.session_state.answered)

if submit and user_choice is not None and not st.session_state.answered:
    st.session_state.answered, is_correct = True, user_choice == q["answer"]
    curr_score = st.session_state.mastery.get(q["topic"], 0.0)

    new_score = min(1.0, curr_score + 0.15) if is_correct else max(0.0, curr_score - 0.20)
    st.session_state.feedback = {
        "type": "success" if is_correct else "error",
        "msg": f"🎉 **Correct!**\n\n{q['explanation']}" if is_correct else f"❌ **Not quite.**\n\n**Correct Answer:** {q['answer']}\n\n💡 **Concept:** {q['explanation']}"
    }
    st.session_state.mastery[q["topic"]] = new_score
    record_attempt(st.session_state.student["id"], q["topic"], q["template_id"], is_correct, user_choice, new_score)

if st.session_state.feedback:
    if st.session_state.feedback["type"] == "success":
        st.success(st.session_state.feedback["msg"])
    else:
        st.error(st.session_state.feedback["msg"])

if st.session_state.answered and st.button("Next Question ➡️"):
    pick_next_question()
    st.rerun()

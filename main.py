from pprint import pprint
from neo4j import GraphDatabase
import pandas as pd
from tqdm import tqdm
import re

# === 1. Load Excel ===
file_path = "scf.xlsx"
df = pd.read_excel(file_path, sheet_name="SCF 2025.2.2")

# Normalize column names
df.columns = [
    re.sub(r"-+", "-", str(c).strip().replace("\n", "-").replace(" ", "-"))
    for c in df.columns
]

# Identify key columns
scf_col = "SCF-#"  # adjust if slightly different
additional_props = [
    "SCF-Domain",
    "SCF-Control",
    "Secure-Controls-Framework-(SCF)-Control-Description",
    "SCF-Control-Question",
    "Relative-Control-Weighting",
    "NIST-CSF-Function-Grouping",
]

# Map to camelCase Neo4j-safe property names
prop_mapping = {
    "SCF-Domain": "scfDomain",
    "SCF-Control": "scfControl",
    "Secure-Controls-Framework-(SCF)-Control-Description": "scfDescription",
    "SCF-Control-Question": "scfControlQuestion",
    "Relative-Control-Weighting": "relativeControlWeighting",
    "NIST-CSF-Function-Grouping": "nistCsfFunctionGrouping",
}

# Framework selection
defined_frameworks = [
    "ISO-27001-v2022",
    "ISO-27002-v2022",
    "EMEA-EU-GDPR",
    "EMEA-EU-DORA",
    "EMEA-EU-NIS2",
    "NIST-CSF-v2.0",
    "ISO-27001-2022",
    "CIS-CSC-v8.1",
]

# Keep only existing frameworks
framework_cols = [col for col in df.columns if col in defined_frameworks]
missing = [col for col in defined_frameworks if col not in df.columns]
if missing:
    print(
        "Warning: The following frameworks were not found in the Excel and will be ignored:"
    )
    for m in missing:
        print("  -", m)

pprint(framework_cols)

# === 2. Reshape into long format ===
df_long = df.melt(
    id_vars=[scf_col] + additional_props,
    value_vars=framework_cols,
    var_name="framework",
    value_name="mapped",
)

# Keep only mapped frameworks
df_long = df_long[
    df_long["mapped"].notna() & (df_long["mapped"] != "") & (df_long["mapped"] != 0)
]

pprint(df_long.columns.to_list())

# === 3. Connect to Neo4j ===
uri = "bolt://localhost:7687"
user = "neo4j"
password = "something_secure"
driver = GraphDatabase.driver(uri, auth=(user, password))


# === 4. Create schema constraints ===
def create_schema(tx):
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Control) REQUIRE c.scfId IS UNIQUE")
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (f:Framework) REQUIRE f.name IS UNIQUE")


with driver.session() as session:
    session.execute_write(create_schema)


# === 5. Insert data with additional properties ===
def add_data(tx, scf_id, framework, props):
    # Dynamic property string for Control node
    prop_str = ", ".join([f"{k}: ${k}" for k in props.keys()])
    query = f"""
        MERGE (c:Control {{scfId: $scfId}})
        SET c += {{{prop_str}}}
        MERGE (f:Framework {{name: $framework}})
        MERGE (f)-[:COVERS]->(c)
    """
    params = {"scfId": scf_id, "framework": framework, **props}
    tx.run(query, **params)


with driver.session() as session:
    for _, row in tqdm(
        df_long.iterrows(), total=df_long.shape[0], desc="Creating Cypher nodes"
    ):
        props = {
            prop_mapping[col]: row[col]
            for col in additional_props
            if col in row and pd.notna(row[col])
        }
        session.execute_write(add_data, row[scf_col], row["framework"], props)

driver.close()

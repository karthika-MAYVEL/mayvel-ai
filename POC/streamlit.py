import streamlit as st
import requests

st.set_page_config(page_title="Seyo AI Tester", layout="wide")

# ---------------------------
# PROFILE DATA
# ---------------------------

PROFILES = [
{
"tenantId":"3a162b9b-5195-fd8d-0fe4-42356e11c031",
"users":[
{"userId":"3a162ba0-6f23-b242-566a-63f8387e045e"},
{"userId":"3a162b9b-52d3-acb9-4448-28a13d492666"}
]
},
{
"tenantId":"3a1829b0-ac0a-0274-0383-ef2db5411df6",
"users":[
{"userId":"3a1829b0-aca4-db7b-7abb-c088ed20263b"},
{"userId":"3a183510-7acd-09a8-57d8-bd533cef07fd"}
]
},
{
"tenantId":"3a168919-279a-96a7-da7e-7788fef6b4d8",
"users":[
{"userId":"3a1756f1-f390-6c4d-d817-b94b1b01e5a2"},
{"userId":"3a175696-f4cc-3d70-1f68-19dcded086ae"},
{"userId":"3a168919-28a9-b0a0-7171-05e1600f29e8"}
]
}
]

DEFAULT_API = "http://localhost:8005/api/v1/ai/ask"

# ---------------------------
# LAYOUT
# ---------------------------

left, right = st.columns([1,3])

# ---------------------------
# LEFT PANEL
# ---------------------------

with left:

    st.title("Profiles")

    tenants = [t["tenantId"] for t in PROFILES]

    tenant = st.selectbox("Tenant", tenants)

    users = []
    for t in PROFILES:
        if t["tenantId"] == tenant:
            users = [u["userId"] for u in t["users"]]

    user = st.selectbox("User", users)

    st.markdown("---")

    api_url = st.text_input("API Endpoint", DEFAULT_API)

# ---------------------------
# RIGHT PANEL
# ---------------------------

with right:

    st.title("Seyo AI Query")

    question = st.text_input(
        "Query",
        placeholder="Example: top failed questions across inspections"
    )

    run = st.button("Execute")

    if run and question:

        payload = {
            "query": question,
            "tenantId": tenant,
            "userId": user
        }

        try:
            response = requests.post(api_url, json=payload).json()
            st.session_state["response"] = response
        except Exception as e:
            st.error(str(e))

    st.markdown("---")

    # ---------------------------
    # RESULTS (same page)
    # ---------------------------

    if "response" in st.session_state:

        response = st.session_state["response"]

        data = response.get("data")

        st.subheader("Results")

        if data:

            if isinstance(data, list):
                st.dataframe(data)
            else:
                st.json(data)

        else:
            st.warning("No results returned")

        # ---------------------------
        # METADATA
        # ---------------------------

        meta = response.get("meta")

        with st.expander("Developer Metadata"):

            if meta:
                st.json(meta)
            else:
                st.write("No metadata available")
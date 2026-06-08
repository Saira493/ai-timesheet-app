import streamlit as st
import mysql.connector
import google.generativeai as genai
import json
from datetime import datetime, date
import pandas as pd
import holidays

# 1. Setup Database Connection using Secure Cloud Secrets
def get_db_connection():
    return mysql.connector.connect(
        host=st.secrets["db_host"],
        user=st.secrets["db_user"],          
        password=st.secrets["db_password"],  
        database=st.secrets["db_name"],
        port=int(st.secrets["db_port"])
    )

# 2. Configure Gemini AI API using Secure Cloud Secrets
GEMINI_KEY = st.secrets["gemini_key"]
genai.configure(api_key=GEMINI_KEY)

def ask_gemini_to_parse(text_input):
    current_year = datetime.now().year
    
    prompt = f"""
    You are an AI timesheet assistant. Extract work dates and locations from this text.
    Return ONLY a valid JSON list of objects. No markdown formatting (DO NOT use ```json blocks), no prose, no conversational text.
    
    If the user gives a date range (e.g., "June 1st to June 5th"), expand it into individual dates for every single day in that range.
    
    Expected Format:
    [
      {{"date": "YYYY-MM-DD", "location": "Location Name"}}
    ]
    
    Current Year: {current_year}
    Employee Text: "{text_input}"
    """
    
    model = genai.GenerativeModel("gemini-flash-latest")
    response = model.generate_content(prompt)
    clean_text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_text)

# Helper function to check if a date qualifies as a payable day
def calculate_billable_status(input_date):
    if isinstance(input_date, str):
        dt = datetime.strptime(input_date, "%Y-%m-%d").date()
    elif isinstance(input_date, datetime):
        dt = input_date.date()
    else:
        dt = input_date

    # 1. Check for Weekends first (Saturday or Sunday)
    if dt.weekday() in [5, 6]:
        return False, "Weekend"
        
    # 2. Check for official UK Bank Holidays falling on a weekday
    uk_holidays = holidays.UnitedKingdom(subdiv='England', years=dt.year)
    if dt in uk_holidays:
        return False, f"Bank Holiday ({uk_holidays.get(dt)})"
        
    return True, "Payable Workday"

# 3. Streamlit UI Dashboard Layout
st.set_page_config(page_title="AI Timesheet System", layout="wide")

# Navigation Sidebar
user_type = st.sidebar.radio("Navigate To:", ["Employee Entry Workspace", "Boss Management Dashboard"])

# --- EMPLOYEE ENTRY INTERFACE ---
if user_type == "Employee Entry Workspace":
    st.title("Smart AI Timesheet System")
    st.subheader("📝 Submit Your Monthly Work Summary")
    st.write("Type your monthly summary naturally. The AI will extract dates and log them automatically.")
    
    employee_name = st.text_input("Your Full Name:")
    employee_text = st.text_area(
        "Describe your work locations:",
        placeholder="e.g., I worked at Alkhair from May 1st to May 5th, and then I spent May 8th to May 12th at Fedilis."
    )
    
    if st.button("Process & Submit Timesheet", type="primary"):
        if employee_name and employee_text:
            with st.spinner("AI is organizing your locations and updating database..."):
                try:
                    parsed_days = ask_gemini_to_parse(employee_text)
                    
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    
                    success_count = 0
                    for entry in parsed_days:
                        try:
                            query = """
                            INSERT INTO daily_records (employee_name, work_date, location)
                            VALUES (%s, %s, %s)
                            ON DUPLICATE KEY UPDATE location = VALUES(location);
                            """
                            cursor.execute(query, (employee_name, entry['date'], entry['location']))
                            success_count += 1
                        except Exception as e:
                            st.warning(f"Skipped saving item {entry}: {str(e)}")
                            
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    st.success(f"🎉 Successfully saved {success_count} days to MySQL for {employee_name}!")
                    st.write("### Extracted Work Log Preview:")
                    st.json(parsed_days)
                    
                except Exception as e:
                    st.error(f"Error processing with AI: {str(e)}")
        else:
            st.error("Please fill in both your name and your work summary text.")

# --- BOSS MANAGEMENT DASHBOARD ---
elif user_type == "Boss Management Dashboard":
    st.title("💼 Enterprise Labor Management Dashboard")
    st.subheader("UK Multi-Site Operations Overview & Payroll Audit")
    st.markdown("---")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT employee_name, work_date, location FROM daily_records ORDER BY work_date DESC")
        records = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Database connection issue: {e}")
        records = []
    
    if not records:
        st.info("No employee timesheets found in the database yet.")
    else:
        # Create core dataframe
        df = pd.DataFrame(records)
        df['work_date'] = pd.to_datetime(df['work_date']).dt.date
        
        # Professional Step: Extract and create clean Month-Year strings for filtering
        # Example: "2026-05-12" converts into a searchable text string: "May 2026"
        df['Month_Year'] = pd.to_datetime(df['work_date']).dt.strftime('%B %Y')
        
        # Apply the weekend & bank holiday filter dynamically
        status_results = df['work_date'].apply(calculate_billable_status)
        df['Is Payable'] = [res[0] for res in status_results]
        df['Day Categorization'] = [res[1] for res in status_results]
        
        # 1. DROP-DOWN FILTERS (Side-by-Side Professional Row)
        st.markdown("### 🔍 Filter Work Records")
        filter_col1, filter_col2 = st.columns(2)
        
        with filter_col1:
            unique_employees = sorted(list(df['employee_name'].unique()))
            selected_emp = st.selectbox("1. Select an Employee:", unique_employees)
            
        with filter_col2:
            # Isolate available months specifically for the selected employee
            emp_months = df[df['employee_name'] == selected_emp]['Month_Year'].unique()
            selected_month = st.selectbox("2. Choose Pay-Period Month:", sorted(list(emp_months)))
        
        st.markdown("---")
        
        if selected_emp and selected_month:
            # Apply both filters at the same time
            filtered_df = df[(df['employee_name'] == selected_emp) & (df['Month_Year'] == selected_month)]
            
            payable_df = filtered_df[filtered_df['Is Payable'] == True]
            
            # Group locations and tally totals ONLY for approved payable days
            summary_df = payable_df.groupby('location').size().reset_index(name='Payable Days')
            summary_df.columns = ['UK Work Location Site', 'Total Days Owed Pay']
            
            total_days_logged = len(filtered_df)
            total_payable_days = summary_df['Total Days Owed Pay'].sum()
            total_excluded_days = total_days_logged - total_payable_days
            
            # Summary metrics panels for the Boss
            st.markdown(f"### 📊 Breakdown for {selected_emp} during **{selected_month}**")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(label="📅 Total Days Logged", value=f"{total_days_logged} Days")
            with col2:
                st.metric(label="💰 Approved Payable Days", value=f"{total_payable_days} Days")
            with col3:
                st.metric(label="🛑 Excluded (Weekends / Bank Holidays)", value=f"{total_excluded_days} Days")
            
            st.markdown("###")
            
            # Render final payroll lookup table
            st.markdown("#### **Approved Payroll Summary Table**")
            if not summary_df.empty:
                st.dataframe(summary_df, use_container_width=True, hide_index=True)
            else:
                st.warning(f"This employee has 0 payable days within {selected_month}.")
            
            st.markdown("###")
            with st.expander("🔍 In-Depth Shift Audit Log (View Classification Breakdown)"):
                audit_display_df = filtered_df[['work_date', 'location', 'Day Categorization', 'Is Payable']].copy()
                audit_display_df.columns = ['Calendar Date', 'Location Site', 'Payroll Classification', 'Paid Status']
                st.dataframe(audit_display_df, use_container_width=True, hide_index=True)


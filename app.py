import streamlit as st
import subprocess
import json
import pandas as pd
import datetime

# Page configuration
st.set_page_config(page_title="CloudCost AI - SaaS Dashboard", page_icon="☁️", layout="wide")

st.title("☁️ CloudCost AI - SaaS Cost Optimization Dashboard")
st.markdown("Automated FinOps tool to detect idle cloud resources, track historical spend trends, and eliminate unnecessary expenses.")

# Sidebar for Region Selection & Cost Explorer
st.sidebar.header("🌍 AWS Configuration")
aws_regions = st.sidebar.multiselect(
    "Select AWS Regions to Scan",
    ["ap-south-1", "us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1", "ap-southeast-2"],
    default=["ap-south-1", "ap-southeast-2"]
)

fetch_cost_history = st.sidebar.checkbox("📈 Fetch 3-Month Cost Explorer Trends", value=True)

# Session state initialization
if "scanned" not in st.session_state:
    st.session_state.scanned = False
    st.session_state.volumes = []
    st.session_state.eips = []
    st.session_state.elbs = []
    st.session_state.instances = []
    st.session_state.cost_data = []

# Function to run scans safely across selected regions
def run_scan(regions, fetch_costs):
    all_volumes = []
    all_eips = []
    all_elbs = []
    all_instances = []
    
    with st.spinner("Scanning AWS infrastructure and fetching Cost Explorer data... Please wait..."):
        for reg in regions:
            # 1. Scan unattached EBS Volumes
            ebs_cmd = f'aws ec2 describe-volumes --region {reg} --filters "Name=status,Values=available" --output json'
            ebs_res = subprocess.run(ebs_cmd, capture_output=True, text=True, shell=True)
            if ebs_res.returncode == 0 and ebs_res.stdout.strip():
                try:
                    data = json.loads(ebs_res.stdout)
                    for v in data.get('Volumes', []):
                        all_volumes.append({
                            'ID': v.get('VolumeId'),
                            'Size': v.get('Size'),
                            'Zone': v.get('AvailabilityZone'),
                            'Region': reg
                        })
                except json.JSONDecodeError:
                    pass

            # 2. Scan unattached Elastic IPs
            eip_cmd = f'aws ec2 describe-addresses --region {reg} --output json'
            eip_res = subprocess.run(eip_cmd, capture_output=True, text=True, shell=True)
            if eip_res.returncode == 0 and eip_res.stdout.strip():
                try:
                    data = json.loads(eip_res.stdout)
                    for addr in data.get('Addresses', []):
                        if 'AssociationId' not in addr:
                            all_eips.append({
                                'PublicIp': addr.get('PublicIp'),
                                'AllocationId': addr.get('AllocationId'),
                                'Region': reg
                            })
                except json.JSONDecodeError:
                    pass

            # 3. Scan Load Balancers
            elb_cmd = f'aws elbv2 describe-load-balancers --region {reg} --output json'
            elb_res = subprocess.run(elb_cmd, capture_output=True, text=True, shell=True)
            if elb_res.returncode == 0 and elb_res.stdout.strip():
                try:
                    data = json.loads(elb_res.stdout)
                    for lb in data.get('LoadBalancers', []):
                        all_elbs.append({
                            'Name': lb.get('LoadBalancerName'),
                            'ARN': lb.get('LoadBalancerArn'),
                            'Scheme': lb.get('Scheme'),
                            'Region': reg
                        })
                except json.JSONDecodeError:
                    pass

            # 4. Scan Stopped EC2 Instances
            ec2_cmd = f'aws ec2 describe-instances --region {reg} --filters "Name=instance-state-name,Values=stopped" --output json'
            ec2_res = subprocess.run(ec2_cmd, capture_output=True, text=True, shell=True)
            if ec2_res.returncode == 0 and ec2_res.stdout.strip():
                try:
                    data = json.loads(ec2_res.stdout)
                    for reservation in data.get('Reservations', []):
                        for inst in reservation.get('Instances', []):
                            all_instances.append({
                                'ID': inst.get('InstanceId'),
                                'Type': inst.get('InstanceType'),
                                'State': inst.get('State', {}).get('Name'),
                                'LaunchTime': inst.get('LaunchTime'),
                                'Region': reg
                            })
                except json.JSONDecodeError:
                    pass

        # Fetch Cost Explorer Data if enabled
        cost_records = []
        if fetch_costs:
            end_date = datetime.date.today().strftime('%Y-%m-%d')
            start_date = (datetime.date.today() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
            ce_cmd = f'aws ce get-cost-and-usage --time-period Start={start_date},End={end_date} --granularity MONTHLY --metrics "UnblendedCost" --output json'
            ce_res = subprocess.run(ce_cmd, capture_output=True, text=True, shell=True)
            if ce_res.returncode == 0 and ce_res.stdout.strip():
                try:
                    ce_data = json.loads(ce_res.stdout)
                    for period in ce_data.get('ResultsByTime', []):
                        start_time = period.get('TimePeriod', {}).get('Start')
                        amount = float(period.get('Total', {}).get('UnblendedCost', {}).get('Amount', 0))
                        cost_records.append({
                            "Month": start_time[:7], # YYYY-MM
                            "Total Spend ($)": round(amount, 2)
                        })
                except json.JSONDecodeError:
                    pass

    st.session_state.volumes = all_volumes
    st.session_state.eips = all_eips
    st.session_state.elbs = all_elbs
    st.session_state.instances = all_instances
    st.session_state.cost_data = cost_records
    st.session_state.scanned = True

if st.button("🚀 Run Cloud Scan Now", type="primary"):
    if not aws_regions:
        st.warning("Please select at least one AWS region from the sidebar.")
    else:
        run_scan(aws_regions, fetch_cost_history)

if st.session_state.scanned:
    volumes = st.session_state.volumes
    eips = st.session_state.eips
    elbs = st.session_state.elbs
    instances = st.session_state.instances
    cost_data = st.session_state.cost_data

    # Display Cost Explorer Trend Chart if available
    if cost_data:
        st.subheader("📈 Historical Cloud Spend Trend (Last 3 Months)")
        df_cost = pd.DataFrame(cost_data)
        st.bar_chart(df_cost.set_index("Month"))
        st.markdown("---")

    total_issues = len(volumes) + len(eips) + len(elbs) + len(instances)

    st.subheader("📊 Scan Results & Multi-Region Resource Analysis")

    if total_issues > 0:
        st.error(f"⚠️ Inefficient or idle resources detected! Found {len(volumes)} EBS volume(s), {len(eips)} unattached EIP(s), {len(elbs)} Load Balancer(s), and {len(instances)} stopped EC2 instance(s).")
        
        with st.expander("View Raw JSON Scan Outputs"):
            st.write("**Stopped EC2 Instances:**")
            st.json(instances)
            st.write("**Unattached Volumes:**")
            st.json(volumes)
            st.write("**Unattached Elastic IPs:**")
            st.json(eips)
            st.write("**Load Balancers:**")
            st.json(elbs)
                
        st.markdown("---")
        st.subheader("🤖 AI FinOps Advisor Report & Cost Impact")
        
        total_ebs_size = sum(v.get('Size', 0) for v in volumes)
        est_ebs_cost = total_ebs_size * 0.08
        est_eip_cost = len(eips) * 3.60
        est_elb_cost = len(elbs) * 18.00
        est_stopped_ec2_cost = len(instances) * 2.40
        
        total_est_waste = est_ebs_cost + est_eip_cost + est_elb_cost + est_stopped_ec2_cost

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(label="Stopped EC2", value=f"{len(instances)} Instance(s)", delta=f"-{len(instances)} VM", delta_color="inverse")
        with col2:
            st.metric(label="Wasted EBS Storage", value=f"{total_ebs_size} GB", delta=f"-{len(volumes)} Vol", delta_color="inverse")
        with col3:
            st.metric(label="Idle Elastic IPs", value=f"{len(eips)} EIP(s)", delta=f"-{len(eips)} IP", delta_color="inverse")
        with col4:
            st.metric(label="Est. Monthly Waste", value=f"${total_est_waste:.2f} / mo", delta="High Priority", delta_color="inverse")
            
        # Export CSV Feature
        st.markdown("---")
        st.subheader("📥 Export FinOps Cost Report")
        
        report_rows = []
        for v in volumes:
            report_rows.append({
                "Resource Type": "EBS Volume",
                "Resource Identifier": v.get('ID'),
                "Region": v.get('Region'),
                "Details": f"{v.get('Size')} GB ({v.get('Zone')})",
                "Est. Monthly Waste ($)": v.get('Size', 0) * 0.08
            })
        for e in eips:
            report_rows.append({
                "Resource Type": "Elastic IP",
                "Resource Identifier": e.get('PublicIp'),
                "Region": e.get('Region'),
                "Details": f"Allocation ID: {e.get('AllocationId')}",
                "Est. Monthly Waste ($)": 3.60
            })
        for lb in elbs:
            report_rows.append({
                "Resource Type": "Load Balancer",
                "Resource Identifier": lb.get('Name'),
                "Region": lb.get('Region'),
                "Details": f"Scheme: {lb.get('Scheme')}",
                "Est. Monthly Waste ($)": 18.00
            })
        for inst in instances:
            report_rows.append({
                "Resource Type": "Stopped EC2",
                "Resource Identifier": inst.get('ID'),
                "Region": inst.get('Region'),
                "Details": f"Type: {inst.get('Type')}",
                "Est. Monthly Waste ($)": 2.40
            })

        df_report = pd.DataFrame(report_rows)
        csv_data = df_report.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label="📥 Download Full FinOps Report (CSV)",
            data=csv_data,
            file_name="CloudCost_AI_FinOps_Report.csv",
            mime="text/csv",
            type="primary"
        )

        st.markdown("---")
        st.subheader("⚡ One-Click Remediation & Cleanup")
        
        enable_cleanup = st.checkbox("⚠️ Enable Risk Mode: Allow resource deletion and release actions from dashboard")

        if enable_cleanup:
            # EBS Cleanup Section
            if volumes:
                st.markdown("#### Unattached EBS Volumes Cleanup")
                for v in volumes:
                    vol_id = v.get('ID')
                    reg = v.get('Region', 'ap-south-1')
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.warning(f"Volume `{vol_id}` ({v.get('Size')} GB) in Region **{reg}** (`{v.get('Zone')}`)")
                    with col_b:
                        if st.button(f"Delete {vol_id}", key=f"del_vol_{vol_id}_{reg}"):
                            del_cmd = f"aws ec2 delete-volume --region {reg} --volume-id {vol_id}"
                            res = subprocess.run(del_cmd, capture_output=True, text=True, shell=True)
                            if res.returncode == 0:
                                st.success(f"Successfully deleted volume {vol_id} from {reg}!")
                                run_scan(aws_regions, fetch_cost_history)
                                st.rerun()
                            else:
                                st.error(f"Error: {res.stderr}")

            # EIP Cleanup Section
            if eips:
                st.markdown("#### Unattached Elastic IPs Cleanup")
                for e in eips:
                    alloc_id = e.get('AllocationId')
                    public_ip = e.get('PublicIp')
                    reg = e.get('Region', 'ap-south-1')
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.warning(f"Public IP `{public_ip}` (Allocation ID: `{alloc_id}`) in Region **{reg}**")
                    with col_b:
                        if st.button(f"Release {public_ip}", key=f"rel_eip_{alloc_id}_{reg}"):
                            rel_cmd = f"aws ec2 release-address --region {reg} --allocation-id {alloc_id}"
                            res = subprocess.run(rel_cmd, capture_output=True, text=True, shell=True)
                            if res.returncode == 0:
                                st.success(f"Successfully released EIP {public_ip} from {reg}!")
                                run_scan(aws_regions, fetch_cost_history)
                                st.rerun()
                            else:
                                st.error(f"Error: {res.stderr}")
        else:
            st.info("💡 Check the 'Enable Risk Mode' checkbox above to unlock direct cleanup and deletion buttons for safe resource management.")

        st.markdown("---")
        st.subheader("📌 Detailed Recommendations")
        for inst in instances:
            st.warning(f"**Stopped EC2 Recommendation:** Instance (`{inst.get('ID')}`) in Region **{inst.get('Region')}** is in **STOPPED** state.")

        for v in volumes:
            st.info(f"**EBS Note:** Unattached volume (`{v.get('ID')}`) in **{v.get('Region')}** is ready for cleanup.")
            
        for e in eips:
            st.info(f"**Elastic IP Note:** Unattached Public IP (`{e.get('PublicIp')}`) in **{e.get('Region')}** can be safely released.")

        for lb in elbs:
            st.info(f"**Load Balancer Review:** Found Load Balancer `{lb.get('Name')}` in **{lb.get('Region')}**.")
    else:
        st.success("🎉 Your cloud is fully optimized across all selected regions! No idle resources detected.")
import datetime
import boto3
import pandas as pd
import streamlit as st

# Page configuration
st.set_page_config(
    page_title="CloudCost AI - SaaS Dashboard", page_icon="☁️", layout="wide"
)

st.title("☁️ CloudCost AI - SaaS Cost Optimization Dashboard")
st.markdown(
    "Automated FinOps tool to detect idle cloud resources, track historical spend trends, and eliminate unnecessary expenses."
)

# Sidebar for Region Selection & Cost Explorer
st.sidebar.header("🌍 AWS Configuration")
aws_regions = st.sidebar.multiselect(
    "Select AWS Regions to Scan",
    [
        "ap-south-1",
        "us-east-1",
        "us-west-2",
        "eu-west-1",
        "ap-southeast-1",
        "ap-southeast-2",
    ],
    default=["ap-south-1", "ap-southeast-2"],
)

fetch_cost_history = st.sidebar.checkbox(
    "📈 Fetch 3-Month Cost Explorer Trends", value=True
)

# Helper function to get boto3 client securely from Streamlit Secrets or environment
def get_boto3_client(service_name, region_name=None):
  try:
    aws_access_key = st.secrets["AWS_ACCESS_KEY_ID"]
    aws_secret_key = st.secrets["AWS_SECRET_ACCESS_KEY"]
    if region_name:
      return boto3.client(
          service_name,
          aws_access_key_id=aws_access_key,
          aws_secret_access_key=aws_secret_key,
          region_name=region_name,
      )
    else:
      return boto3.client(
          service_name,
          aws_access_key_id=aws_access_key,
          aws_secret_access_key=aws_secret_key,
      )
  except Exception:
    if region_name:
      return boto3.client(service_name, region_name=region_name)
    return boto3.client(service_name)


# Session state initialization
if "scanned" not in st.session_state:
  st.session_state.scanned = False
  st.session_state.volumes = []
  st.session_state.eips = []
  st.session_state.elbs = []
  st.session_state.instances = []
  st.session_state.s3_buckets = []
  st.session_state.cost_data = []


# Function to run scans safely using boto3 across selected regions
def run_scan(regions, fetch_costs):
  all_volumes = []
  all_eips = []
  all_elbs = []
  all_instances = []
  all_s3_buckets = []

  with st.spinner(
      "Scanning AWS infrastructure (EC2, ELB, S3) via Boto3 and fetching Cost"
      " Explorer data... Please wait..."
  ):
    # 1. Scan S3 Buckets (Global Service)
    try:
      s3_client = get_boto3_client("s3")
      buckets_res = s3_client.list_buckets()
      for b in buckets_res.get("Buckets", []):
        b_name = b.get("Name")
        try:
          loc_res = s3_client.get_bucket_location(Bucket=b_name)
          reg = loc_res.get("LocationConstraint") or "us-east-1"
          if reg == "EU":
            reg = "eu-west-1"
        except Exception:
          reg = "us-east-1"

        # Check if bucket matches selected regions or include all
        if reg in regions or not regions:
          # Check Lifecycle configuration
          has_lifecycle = True
          try:
            s3_client.get_bucket_lifecycle_configuration(Bucket=b_name)
          except Exception:
            has_lifecycle = False

          all_s3_buckets.append({
              "Name": b_name,
              "Region": reg,
              "CreationDate": (
                  b.get("CreationDate").strftime("%Y-%m-%d")
                  if b.get("CreationDate")
                  else "N/A"
              ),
              "HasLifecycle": has_lifecycle,
          })
    except Exception as e:
      st.error(f"Error scanning S3 buckets: {e}")

    # 2. Scan Regional EC2 and ELB Resources
    for reg in regions:
      try:
        ec2 = get_boto3_client("ec2", reg)
        elbv2 = get_boto3_client("elbv2", reg)

        # Unattached EBS Volumes
        ebs_res = ec2.describe_volumes(
            Filters=[{"Name": "status", "Values": ["available"]}]
        )
        for v in ebs_res.get("Volumes", []):
          all_volumes.append({
              "ID": v.get("VolumeId"),
              "Size": v.get("Size"),
              "Zone": v.get("AvailabilityZone"),
              "Region": reg,
          })

        # Unattached Elastic IPs
        eip_res = ec2.describe_addresses()
        for addr in eip_res.get("Addresses", []):
          if "AssociationId" not in addr:
            all_eips.append({
                "PublicIp": addr.get("PublicIp"),
                "AllocationId": addr.get("AllocationId"),
                "Region": reg,
            })

        # Load Balancers
        elb_res = elbv2.describe_load_balancers()
        for lb in elb_res.get("LoadBalancers", []):
          all_elbs.append({
              "Name": lb.get("LoadBalancerName"),
              "ARN": lb.get("LoadBalancerArn"),
              "Scheme": lb.get("Scheme"),
              "Region": reg,
          })

        # Stopped EC2 Instances
        ec2_res = ec2.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
        )
        for reservation in ec2_res.get("Reservations", []):
          for inst in reservation.get("Instances", []):
            launch_time = inst.get("LaunchTime")
            launch_time_str = (
                launch_time.strftime("%Y-%m-%d %H:%M:%S")
                if launch_time
                else "N/A"
            )
            all_instances.append({
                "ID": inst.get("InstanceId"),
                "Type": inst.get("InstanceType"),
                "State": inst.get("State", {}).get("Name"),
                "LaunchTime": launch_time_str,
                "Region": reg,
            })
      except Exception as e:
        st.error(f"Error scanning region {reg}: {e}")

    # Fetch Cost Explorer Data if enabled
    cost_records = []
    if fetch_costs:
      try:
        ce = get_boto3_client("ce", "us-east-1")
        end_date = datetime.date.today().strftime("%Y-%m-%d")
        start_date = (
            datetime.date.today() - datetime.timedelta(days=90)
        ).strftime("%Y-%m-%d")

        ce_res = ce.get_cost_and_usage(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )
        for period in ce_res.get("ResultsByTime", []):
          start_time = period.get("TimePeriod", {}).get("Start")
          amount = float(
              period.get("Total", {})
              .get("UnblendedCost", {})
              .get("Amount", 0)
          )
          cost_records.append({
              "Month": start_time[:7],
              "Total Spend ($)": round(amount, 2),
          })
      except Exception:
        pass

  st.session_state.volumes = all_volumes
  st.session_state.eips = all_eips
  st.session_state.elbs = all_elbs
  st.session_state.instances = all_instances
  st.session_state.s3_buckets = all_s3_buckets
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
  s3_buckets = st.session_state.s3_buckets
  cost_data = st.session_state.cost_data

  # Display Cost Explorer Trend Chart if available
  if cost_data:
    st.subheader("📈 Historical Cloud Spend Trend (Last 3 Months)")
    df_cost = pd.DataFrame(cost_data)
    st.bar_chart(df_cost.set_index("Month"))
    st.markdown("---")

  total_issues = (
      len(volumes)
      + len(eips)
      + len(elbs)
      + len(instances)
      + len([b for b in s3_buckets if not b["HasLifecycle"]])
  )

  st.subheader("📊 Scan Results & Multi-Region Resource Analysis")

  if total_issues > 0:
    st.error(
        f"⚠️ Inefficient or idle resources detected! Found {len(volumes)} EBS"
        f" volume(s), {len(eips)} unattached EIP(s), {len(elbs)} Load"
        f" Balancer(s), {len(instances)} stopped EC2 instance(s), and"
        f" {len([b for b in s3_buckets if not b['HasLifecycle']])} S3"
        f" bucket(s) missing lifecycle policies."
    )

    with st.expander("View Raw JSON Scan Outputs"):
      st.write("**Stopped EC2 Instances:**")
      st.json(instances)
      st.write("**Unattached Volumes:**")
      st.json(volumes)
      st.write("**Unattached Elastic IPs:**")
      st.json(eips)
      st.write("**Load Balancers:**")
      st.json(elbs)
      st.write("**S3 Buckets Analysis:**")
      st.json(s3_buckets)

    st.markdown("---")
    st.subheader("🤖 AI FinOps Advisor Report & Cost Impact")

    total_ebs_size = sum(v.get("Size", 0) for v in volumes)
    est_ebs_cost = total_ebs_size * 0.08
    est_eip_cost = len(eips) * 3.60
    est_elb_cost = len(elbs) * 18.00
    est_stopped_ec2_cost = len(instances) * 2.40
    est_s3_waste = (
        len([b for b in s3_buckets if not b["HasLifecycle"]]) * 10.00
    )  # Estimated optimization potential

    total_est_waste = (
        est_ebs_cost
        + est_eip_cost
        + est_elb_cost
        + est_stopped_ec2_cost
        + est_s3_waste
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
      st.metric(
          label="Stopped EC2",
          value=f"{len(instances)} Instance(s)",
          delta=f"-{len(instances)} VM",
          delta_color="inverse",
      )
    with col2:
      st.metric(
          label="Wasted EBS Storage",
          value=f"{total_ebs_size} GB",
          delta=f"-{len(volumes)} Vol",
          delta_color="inverse",
      )
    with col3:
      st.metric(
          label="S3 Without Lifecycle",
          value=f"{len([b for b in s3_buckets if not b['HasLifecycle']])} Bucket(s)",
          delta="Optimization Needed",
          delta_color="inverse",
      )
    with col4:
      st.metric(
          label="Est. Monthly Waste",
          value=f"${total_est_waste:.2f} / mo",
          delta="High Priority",
          delta_color="inverse",
      )

    # Export CSV Feature
    st.markdown("---")
    st.subheader("📥 Export FinOps Cost Report")

    report_rows = []
    for v in volumes:
      report_rows.append({
          "Resource Type": "EBS Volume",
          "Resource Identifier": v.get("ID"),
          "Region": v.get("Region"),
          "Details": f"{v.get('Size')} GB ({v.get('Zone')})",
          "Est. Monthly Waste ($)": v.get("Size", 0) * 0.08,
      })
    for e in eips:
      report_rows.append({
          "Resource Type": "Elastic IP",
          "Resource Identifier": e.get("PublicIp"),
          "Region": e.get("Region"),
          "Details": f"Allocation ID: {e.get('AllocationId')}",
          "Est. Monthly Waste ($)": 3.60,
      })
    for lb in elbs:
      report_rows.append({
          "Resource Type": "Load Balancer",
          "Resource Identifier": lb.get("Name"),
          "Region": lb.get("Region"),
          "Details": f"Scheme: {lb.get('Scheme')}",
          "Est. Monthly Waste ($)": 18.00,
      })
    for inst in instances:
      report_rows.append({
          "Resource Type": "Stopped EC2",
          "Resource Identifier": inst.get("ID"),
          "Region": inst.get("Region"),
          "Details": f"Type: {inst.get('Type')}",
          "Est. Monthly Waste ($)": 2.40,
      })
    for b in s3_buckets:
      if not b["HasLifecycle"]:
        report_rows.append({
            "Resource Type": "S3 Bucket (No Lifecycle)",
            "Resource Identifier": b["Name"],
            "Region": b["Region"],
            "Details": f"Created: {b['CreationDate']}",
            "Est. Monthly Waste ($)": 10.00,
        })

    df_report = pd.DataFrame(report_rows)
    csv_data = df_report.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="📥 Download Full FinOps Report (CSV)",
        data=csv_data,
        file_name="CloudCost_AI_FinOps_Report.csv",
        mime="text/csv",
        type="primary",
    )

    st.markdown("---")
    st.subheader("⚡ One-Click Remediation & Cleanup")

    enable_cleanup = st.checkbox(
        "⚠️ Enable Risk Mode: Allow resource deletion and release actions from"
        " dashboard"
    )

    if enable_cleanup:
      if volumes:
        st.markdown("#### Unattached EBS Volumes Cleanup")
        for v in volumes:
          vol_id = v.get("ID")
          reg = v.get("Region", "ap-south-1")
          col_a, col_b = st.columns([3, 1])
          with col_a:
            st.warning(
                f"Volume `{vol_id}` ({v.get('Size')} GB) in Region **{reg}**"
                f" (`{v.get('Zone')}`)"
            )
          with col_b:
            if st.button(f"Delete {vol_id}", key=f"del_vol_{vol_id}_{reg}"):
              try:
                ec2_del = get_boto3_client("ec2", reg)
                ec2_del.delete_volume(VolumeId=vol_id)
                st.success(f"Successfully deleted volume {vol_id} from {reg}!")
                run_scan(aws_regions, fetch_cost_history)
                st.rerun()
              except Exception as e:
                st.error(f"Error: {e}")

      if eips:
        st.markdown("#### Unattached Elastic IPs Cleanup")
        for e in eips:
          alloc_id = e.get("AllocationId")
          public_ip = e.get("PublicIp")
          reg = e.get("Region", "ap-south-1")
          col_a, col_b = st.columns([3, 1])
          with col_a:
            st.warning(
                f"Public IP `{public_ip}` (Allocation ID: `{alloc_id}`) in"
                f" Region **{reg}**"
            )
          with col_b:
            if st.button(f"Release {public_ip}", key=f"rel_eip_{alloc_id}_{reg}"):
              try:
                ec2_rel = get_boto3_client("ec2", reg)
                ec2_rel.release_address(AllocationId=alloc_id)
                st.success(
                    f"Successfully released EIP {public_ip} from {reg}!"
                )
                run_scan(aws_regions, fetch_cost_history)
                st.rerun()
              except Exception as e:
                st.error(f"Error: {e}")
    else:
      st.info(
          "💡 Check the 'Enable Risk Mode' checkbox above to unlock direct"
          " cleanup and deletion buttons for safe resource management."
      )

    st.markdown("---")
    st.subheader("📌 Detailed Recommendations & S3 Governance")
    for b in s3_buckets:
      if not b["HasLifecycle"]:
        st.warning(
            f"**S3 Lifecycle Recommendation:** Bucket `{b['Name']}` in Region"
            f" **{b['Region']}** does not have a Lifecycle Policy configured."
            " Consider adding rules to transition old objects to Glacier or"
            " delete incomplete multipart uploads."
        )
      else:
        st.info(
            f"**S3 Governance OK:** Bucket `{b['Name']}` in Region"
            f" **{b['Region']}** has lifecycle rules configured."
        )

    for inst in instances:
      st.warning(
          f"**Stopped EC2 Recommendation:** Instance (`{inst.get('ID')}`) in"
          f" Region **{inst.get('Region')}** is in **STOPPED** state."
      )

    for v in volumes:
      st.info(
          f"**EBS Note:** Unattached volume (`{v.get('ID')}`) in"
          f" **{v.get('Region')}** is ready for cleanup."
      )

    for e in eips:
      st.info(
          f"**Elastic IP Note:** Unattached Public IP (`{e.get('PublicIp')}`)"
          f" in **{e.get('Region')}** can be safely released."
      )

    for lb in elbs:
      st.info(
          f"**Load Balancer Review:** Found Load Balancer `{lb.get('Name')}` in"
          f" **{lb.get('Region')}**."
      )
  else:
    st.success(
        "🎉 Your cloud is fully optimized across all selected regions! No idle"
        " resources detected."
    )
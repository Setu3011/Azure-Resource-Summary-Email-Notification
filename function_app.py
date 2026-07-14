import os
import json
import logging
import requests
from collections import defaultdict

import azure.functions as func

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.communication.email import EmailClient


#-------------------------------
# Function App
#--------------------------------

app = func.FunctionApp()

#------------------------------
# Environment Variables
#------------------------------

SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
RESOURCE_GROUP_NAME = os.getenv("RESOURCE_GROUP_NAME")

COMMUNICATION_SERVICES_CONNECTION_STRING = os.getenv(
    "COMMUNICATION_SERVICES_CONNECTION_STRING"
)

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

# --------------------------------
# Authentication
# --------------------------------

credential = DefaultAzureCredential()

resource_client = None
email_client = None


def get_resource_client():
    global resource_client

    if resource_client is None:
        resource_client = ResourceManagementClient(
            credential,
            SUBSCRIPTION_ID
        )

    return resource_client


def get_email_client():
    global email_client

    if email_client is None:
        email_client = EmailClient.from_connection_string(
            COMMUNICATION_SERVICES_CONNECTION_STRING
        )

    return email_client

# --------------------------------
# Azure Resource Type Mapping
# --------------------------------

SERVICE_MAPPING = {

    "Microsoft.Compute/virtualMachines":
        "Virtual Machine",

    "Microsoft.Storage/storageAccounts":
        "Storage Account",

    "Microsoft.Network/virtualNetworks":
        "Virtual Network",

    "Microsoft.Network/networkSecurityGroups":
        "Network Security Group",

    "Microsoft.Network/publicIPAddresses":
        "Public IP",

    "Microsoft.Network/loadBalancers":
        "Load Balancer",

    "Microsoft.Network/applicationGateways":
        "Application Gateway",

    "Microsoft.Network/networkInterfaces":
        "Network Interface",

    "Microsoft.Web/sites":
        "App Service",

    "Microsoft.ContainerRegistry/registries":
        "Container Registry",

    "Microsoft.ContainerInstance/containerGroups":
        "Container Instance",

    "Microsoft.ContainerService/managedClusters":
        "AKS Cluster",

    "Microsoft.DBforPostgreSQL/flexibleServers":
        "PostgreSQL Flexible Server",

    "Microsoft.Sql/servers":
        "SQL Server",

    "Microsoft.Sql/servers/databases":
        "SQL Database",

    "Microsoft.KeyVault/vaults":
        "Key Vault",

    "Microsoft.Cache/Redis":
        "Azure Redis Cache",

    "Microsoft.Web/serverfarms":
        "App Service Plan",

    "Microsoft.Insights/components":
        "Application Insights",

    "Microsoft.OperationalInsights/workspaces":
        "Log Analytics Workspace",

    "Microsoft.EventHub/namespaces":
        "Event Hub",

    "Microsoft.ServiceBus/namespaces":
        "Service Bus",

    "Microsoft.DocumentDB/databaseAccounts":
        "Cosmos DB",

    "Microsoft.Storage/storageAccounts/blobServices":
        "Blob Service",

    "Microsoft.Storage/storageAccounts/fileServices":
        "File Service",

    "Microsoft.Network/dnsZones":
        "DNS Zone",

    "Microsoft.Cdn/profiles":
        "CDN",

    "Microsoft.ApiManagement/service":
        "API Management"

}

# --------------------------------
# Validate Configuration
# --------------------------------

def validate_environment():

    required = {
        "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION_ID,
        "RESOURCE_GROUP_NAME": RESOURCE_GROUP_NAME,
        "COMMUNICATION_SERVICES_CONNECTION_STRING":
            COMMUNICATION_SERVICES_CONNECTION_STRING,
        "SENDER_EMAIL": SENDER_EMAIL,
        "RECIPIENT_EMAIL": RECIPIENT_EMAIL
    }

    missing = []

    for key, value in required.items():

        if not value:
            missing.append(key)

    if missing:

        raise Exception(
            "Missing Environment Variables:\n"
            + "\n".join(missing)
        )

# --------------------------------
# Get Azure Access Token
# --------------------------------

def get_access_token():

    token = credential.get_token(
        "https://management.azure.com/.default"
    )

    return token.token

# --------------------------------
# Get All Resources
# --------------------------------

def get_all_resources():

    logging.info(
        "Collecting Azure Resources..."
    )

    resources = []

    result = get_resource_client().resources.list_by_resource_group(
        RESOURCE_GROUP_NAME
    )

    for resource in result:

        service = SERVICE_MAPPING.get(
            resource.type,
            resource.type.split("/")[-1]
        )

        resources.append({

            "id": resource.id,

            "name": resource.name,

            "type": resource.type,

            "service": service,

            "location": resource.location

        })

    logging.info(
        "Total Resources Found : %s",
        len(resources)
    )

    return resources

# --------------------------------
# Group Resources by Service
# --------------------------------

def group_resources(resources):

    grouped = defaultdict(list)

    for resource in resources:

        grouped[
            resource["service"]
        ].append(resource)

    return grouped

# -------------------------
# Format Currency
# -------------------------
def format_cost(cost):
    return f"₹{cost:,.2f} INR"     # (Cost in INR)

# --------------------------------
# Logging Helper
# ----------------------------------

def log_resource_summary(resources):

    logging.info("")

    logging.info(
        "=========== Resource Summary ==========="
    )

    for resource in resources:

        logging.info(
            "%s | %s",
            resource["service"],
            resource["name"]
        )

    logging.info(
        "========================================"
    )
# -------------------------------------------------
#       FUNCTION
# ------------------------------------------------


def get_cost_by_resource():
    """
    Query Azure Cost Management (Month-to-Date) grouped by ResourceId.
    Returns:
        {
            "<resource_id_lower>": cost_float,
            ...
        }
    """
    token = get_access_token()

    url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}"
        "/providers/Microsoft.CostManagement/query"
        "?api-version=2023-11-01"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {
            "from": "2026-07-01T00:00:00+00:00",
            "to": "2026-07-31T23:59:59+00:00"
        },
        "dataset": {
            "granularity": "None",
            "aggregation": {
                "totalCost": {
                    "name": "Cost",
                    "function": "Sum"
                }
            },
            "grouping": [
                {
                    "type": "Dimension",
                    "name": "ResourceId"
                }
            ],
            "filter": {
                "dimensions": {
                    "name": "ResourceGroupName",
                    "operator": "In",
                    "values": [
                        RESOURCE_GROUP_NAME
                    ]
                }
            }
        }
    }

    logging.info("Querying Azure Cost Management API...")

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=120
    )

    if response.status_code != 200:
        logging.error(response.text)
        raise Exception(
            f"Cost API Error: {response.status_code}"
        )

    result = response.json()

    properties = result.get("properties", {})
    columns = properties.get("columns", [])
    rows = properties.get("rows", [])

    logging.info("Columns: %s", columns)
    logging.info("Total Rows Returned: %d", len(rows))

    for row in rows:
        logging.info(row)

    column_index = {}

    for index, column in enumerate(columns):
        column_index[column["name"]] = index

    if "ResourceId" not in column_index:
        raise Exception("ResourceId column missing.")

    resource_idx = column_index["ResourceId"]

    if "Cost" in column_index:
        cost_idx = column_index["Cost"]
    elif "PreTaxCost" in column_index:
        cost_idx = column_index["PreTaxCost"]
    elif "CostUSD" in column_index:
        cost_idx = column_index["CostUSD"]
    else:
        raise Exception(
            f"No supported cost column found. Available columns: {list(column_index.keys())}"
        )

    cost_lookup = {}

    for row in rows:

        resource_id = str(row[resource_idx]).lower()

        try:
            cost = float(row[cost_idx])
        except Exception:
            cost = 0.0

        cost_lookup[resource_id] = round(
            cost_lookup.get(resource_id, 0.0) + cost,
            2
        )

    logging.info(
        "Retrieved %s cost records",
        len(cost_lookup)
    )

    return cost_lookup

def merge_resources_with_cost(resources, cost_lookup):
    """
    Add cost to every resource.
    """

    total_cost = 0.0

    for resource in resources:

        resource_id = resource["id"].lower()

        cost = cost_lookup.get(resource_id, 0.0)

        resource["cost"] = cost

        total_cost += cost

    resources.sort(
        key=lambda x: (
            x["service"].lower(),
            x["name"].lower()
        )
    )

    logging.info(
        "Calculated Total Cost : %s",
        format_cost(total_cost)
    )

    return resources, round(total_cost, 2)


def build_summary(resources):
    """
    Returns grouped resources and statistics.
    """

    grouped = group_resources(resources)

    total_resources = len(resources)

    total_cost = sum(
        r["cost"]
        for r in resources
    )

    return {
        "grouped": grouped,
        "total_resources": total_resources,
        "total_cost": round(total_cost, 2)
    }


def log_cost_summary(resources):

    logging.info("")
    logging.info("========== Resource Costs ==========")

    for resource in resources:

        logging.info(
            "%-25s %-30s %10s",
            resource["service"],
            resource["name"],
            format_cost(resource["cost"])
        )

    logging.info("====================================")


def collect_resource_report():
    """
    Main collection function.
    """

    resources = get_all_resources()

    cost_lookup = get_cost_by_resource()

    resources, _ = merge_resources_with_cost(
        resources,
        cost_lookup
    )
  
    log_resource_summary(resources)
 
    log_cost_summary(resources)

    report = build_summary(resources)

    report["resources"] = resources

    return report

from html import escape

def build_html_email(report):
    """
    Build HTML email from report returned by collect_resource_report().
    """

    grouped = report["grouped"]
    total_resources = report["total_resources"]
    total_cost = report["total_cost"]

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    font-family: Arial, Helvetica, sans-serif;
    background:#f5f7fb;
    color:#333;
}}
.container {{
    max-width:900px;
    margin:auto;
    background:#fff;
    padding:25px;
}}
h2 {{
    color:#0078D4;
}}
table {{
    width:100%;
    border-collapse:collapse;
}}
th {{
    background:#0078D4;
    color:white;
    padding:10px;
    border:1px solid #d9d9d9;
}}
td {{
    padding:10px;
    border:1px solid #d9d9d9;
}}
.service {{
    font-weight:bold;
    background:#f4f9ff;
}}
.total {{
    font-weight:bold;
    background:#eef6ee;
}}
.footer {{
    margin-top:20px;
    color:#666;
    font-size:12px;
}}
</style>
</head>
<body>
<div class="container">

<h2>Azure Resource Group Summary</h2>

<p>
<b>Resource Group:</b> {escape(RESOURCE_GROUP_NAME)}
</p>

<p>
<b>Total Resources:</b> {total_resources}<br>
<b>Total Cost (MTD):</b> {format_cost(total_cost)}
</p>

<table>

<tr>
<th>Service Name</th>
<th>Resource Name</th>
<th>Location</th>
<th>Cost</th>
</tr>
"""

    for service in sorted(grouped.keys()):

        resources = sorted(
            grouped[service],
            key=lambda x: x["name"].lower()
        )

        rowspan = len(resources)

        for index, resource in enumerate(resources):

            html += "<tr>"

            if index == 0:
                html += (
                    f'<td class="service" rowspan="{rowspan}">'
                    f'{escape(service)}</td>'
                )

            html += f"<td>{escape(resource['name'])}</td>"
            html += f"<td>{escape(resource['location'])}</td>"
            html += f"<td>{format_cost(resource['cost'])}</td>"
            html += "</tr>"

    html += f"""
<tr class="total">
<td colspan="3" align="right">Total Cost</td>
<td>{format_cost(total_cost)}</td>
</tr>

</table>

<div class="footer">
Generated automatically by Azure Function.<br>
Month-to-Date cost is based on Azure Cost Management API.
</div>

</div>
</body>
</html>
"""

    return html


def build_plain_text_email(report):
    """
    Plain-text fallback email.
    """

    grouped = report["grouped"]

    lines = []

    lines.append("AZURE RESOURCE GROUP SUMMARY")
    lines.append("=" * 70)
    lines.append(f"Resource Group : {RESOURCE_GROUP_NAME}")
    lines.append(f"Total Resources : {report['total_resources']}")
    lines.append(f"Total Cost : {format_cost(report['total_cost'])}")
    lines.append("")

    for service in sorted(grouped.keys()):

        lines.append(service)
        lines.append("-" * len(service))

        for resource in sorted(
            grouped[service],
            key=lambda x: x["name"].lower()
        ):

            lines.append(
                f"  {resource['name']} | "
                f"{resource['location']} | "
                f"{format_cost(resource['cost'])}"
            )

        lines.append("")

    lines.append("=" * 70)
    lines.append("Generated automatically by Azure Function.")

    return "\n".join(lines)


def build_email_content(report):
    """
    Returns both HTML and plain text.
    """

    return {
        "subject": f"Azure Resource Group Summary - {RESOURCE_GROUP_NAME}",
        "html": build_html_email(report),
        "plain": build_plain_text_email(report),
    }

import traceback

def send_summary_email(report):
    """
    Sends the Resource Group summary email using
    Azure Communication Services.
    """

    email = build_email_content(report)

    message = {
        "senderAddress": SENDER_EMAIL,
        "recipients": {
            "to": [
                {
                    "address": RECIPIENT_EMAIL
                }
            ]
        },
        "content": {
            "subject": email["subject"],
            "plainText": email["plain"],
            "html": email["html"]
        }
    }

    logging.info("Sending email to %s", RECIPIENT_EMAIL)

    poller = get_email_client().begin_send(message)

    result = poller.result()

    logging.info("Email successfully sent.")
    logging.info(result)

    return result

@app.timer_trigger(
    # schedule="0 0 */2 * * *", # Triggers every 2 hours 
    schedule="0 * * * * *", # Triggers every minute for testing
  # schedule="*/2 * * * *", # Triggers every 2 minutes for testing
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False
)
def resource_summary(myTimer: func.TimerRequest) -> None:
    """
    Executes every 2 hours.
    """

    logging.info("=" * 80)
    logging.info("Azure Resource Summary Timer Trigger Started")

    if myTimer.past_due:
        logging.warning("Timer execution is past due.")

    try:

        validate_environment()

        logging.info("Environment variables validated.")

        report = collect_resource_report()

        logging.info(
            "Resources Collected : %s",
            report["total_resources"]
        )

        logging.info(
            "Total Cost : %s",
            format_cost(report["total_cost"])
        )
        
        send_summary_email(report)

        logging.info("Execution completed successfully.")

    except Exception as ex:

        logging.error("Execution failed.")

        logging.error(str(ex))

        logging.error(traceback.format_exc())

        raise

    finally:

        logging.info("Azure Resource Summary Timer Trigger Finished")
        logging.info("=" * 80)

from flask import Flask, request, jsonify, Response
import requests
import logging
from xml.etree import ElementTree as ET
import re
import xml.etree.ElementTree as ET
from flask import request, jsonify


app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


class TallyService:

    def __init__(
        self,
        host='43.kcloud.in',
        port=43087,
        protocol="http",
        timeout=15
    ):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.timeout = timeout

    @property
    def url(self):
        return f"{self.protocol}://{self.host}:{self.port}"

    def send_xml(self, xml_data):

        try:
            logger.info(f"Connecting to Tally: {self.url}")

            response = requests.post(
                self.url,
                data=xml_data.encode("utf-8"),
                headers={
                    "Content-Type": "application/xml"
                },
                timeout=self.timeout
            )

            logger.info(
                f"Tally response status: {response.status_code}"
            )

            return {
                "success": response.ok,
                "status_code": response.status_code,
                "response": response.text
            }

        except requests.exceptions.ConnectionError as e:

            logger.error(f"Connection error: {str(e)}")

            return {
                "success": False,
                "error": "Unable to connect to TallyPrime",
                "details": str(e)
            }

        except requests.exceptions.Timeout:

            logger.error("TallyPrime connection timeout")

            return {
                "success": False,
                "error": "Connection timeout"
            }

        except Exception as e:

            logger.exception("Unexpected error")

            return {
                "success": False,
                "error": str(e)
            }



def clean_tally_xml(xml_data):

    # Remove invalid numeric XML character references
    # Example: &#4;, &#0;, &#1; ... etc.
    xml_data = re.sub(
        r'&#(?:[0-8]|1[0-9]|2[0-9]|3[01]);',
        '',
        xml_data
    )

    # Remove invalid XML control characters
    xml_data = re.sub(
        r'[\x00-\x08\x0B\x0C\x0E-\x1F]',
        '',
        xml_data
    )

    return xml_data


@app.route("/report", methods=["POST"])
def get_company_report():

    data = request.get_json(silent=True) or {}

    host = data.get("host") or "43.kcloud.in"
    port = data.get("port") or 43089

    company_name = data.get("company_name")
    report_name = data.get("report_name")

    if not company_name or not report_name:
        return jsonify({
            "success": False,
            "error": "Both 'company_name' and 'report_name' are required"
        }), 400

    try:

        tally = TallyService(
            host=host,
            port=int(port)
        )
        xml_request = f"""
        <ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>Ledger</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVEXPORTFORMAT>XML</SVEXPORTFORMAT>
                <SVCURRENTCOMPANY>Test</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
    </BODY>
</ENVELOPE>
            """
        
        # xml_request = f"""
        # <ENVELOPE>
        #     <HEADER>
        #         <VERSION>1</VERSION>
        #         <TALLYREQUEST>EXPORT</TALLYREQUEST>
        #         <TYPE>DATA</TYPE>
        #         <ID>{report_name}</ID>
        #     </HEADER>

        #     <BODY>
        #         <DESC>
        #             <STATICVARIABLES>
        #                 <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        #                 <SVCURRENTCOMPANY>{company_name}</SVCURRENTCOMPANY>
        #             </STATICVARIABLES>
        #         </DESC>
        #     </BODY>
        # </ENVELOPE>
        # """

        result = tally.send_xml(xml_request)

        if not result.get("success"):

            return jsonify({
                "success": False,
                "error": result.get(
                    "error",
                    "Failed to get response from Tally"
                )
            }), 500

        xml_response = result.get("response")

        if not xml_response:

            return jsonify({
                "success": False,
                "error": "Empty response received from Tally"
            }), 500

        # IMPORTANT: Clean invalid Tally XML
        cleaned_xml = clean_tally_xml(xml_response)

        # Parse cleaned XML
        root = ET.fromstring(cleaned_xml)

        def xml_to_dict(element):

            children = list(element)

            # Leaf node
            if not children:

                text = element.text.strip() if element.text else ""

                if element.attrib:
                    return {
                        "@attributes": dict(element.attrib),
                        "#text": text
                    }

                return text

            result_dict = {}

            # Add attributes
            if element.attrib:
                result_dict["@attributes"] = dict(element.attrib)

            # Process children
            for child in children:

                tag = child.tag
                child_data = xml_to_dict(child)

                # First occurrence
                if tag not in result_dict:

                    result_dict[tag] = child_data

                # Repeated tag -> list
                else:

                    if not isinstance(result_dict[tag], list):

                        result_dict[tag] = [
                            result_dict[tag]
                        ]

                    result_dict[tag].append(child_data)

            return result_dict

        # Final dictionary
        json_data = {
            root.tag: xml_to_dict(root)
        }

        return jsonify({
            "success": True,
            "company_name": company_name,
            "report_name": report_name,
            "data": json_data
        }), 200

    except ET.ParseError as e:

        return jsonify({
            "success": False,
            "error": "Invalid XML response received from Tally",
            "details": str(e),
            "raw_response": (
                xml_response
                if 'xml_response' in locals()
                else None
            )
        }), 500

    except Exception as e:

        return jsonify({
            "success": False,
            "error": "Internal server error",
            "details": str(e)
        }), 500

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "success": True,
        "service": "Flask TallyPrime API",
        "status": "running"
    })


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5008,
        debug=True
    )




     # NEW: Auto-sync for Tally immediately
#                 tally_sync_result = None
#                 if db_type == 'tally' and user_db_name:
#                     from database.tally_connector import sync_tally_database
#                     try:
#                         print("[*] Triggering Auto-Sync for Tally after connection creation...")
#                         tally_sync_result = sync_tally_database(user_id, new_connection_id, user_session_id, clean_cred_data, user_db_name, username_for_sync)
#                     except Exception as sync_e:
#                         print(f"[!] Auto-Sync failed for Tally: {sync_e}")
#                         tally_sync_result = {"error": str(sync_e)}


# if 'tally_sync_result' in locals() and tally_sync_result:
#             response_data["tally_sync_result"] = tally_sync_result
#             response_data["message"] += " (Data fetched and saved successfully!)"
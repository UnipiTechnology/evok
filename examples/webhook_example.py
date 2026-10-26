"""A receiver of the webhook of Evok, see docs/apis/webhook.md

The configuration of Evok:

    apis:
      webhook:
        enabled: true
        address: http://127.0.0.1:8181
        device_mask: ["di", "led"]
        complex_events: true

With complex_events Evok posts the list of the changed states, without it an empty GET.
"""

from flask import Flask, request

app = Flask(__name__)


@app.route("/", methods=["POST", "GET"])
def respond():
    if request.method == "POST":
        print(request.get_json(silent=True))
    else:
        print("a change")
    return {"status": "success"}, 200


if __name__ == "__main__":
    # not 8080, the port of Evok
    app.run(host="127.0.0.1", port=8181)

"""
The Compute API is a separate Flask app that runs on a separate port. 
It is designed to be run on a separate server from the main PolicyEngine web app, so that it can
be used for compute-intensive tasks without affecting the main server.
"""

import flask
from flask_cors import CORS
from policyengine_api.constants import GET, POST, VERSION
from policyengine_api.country import PolicyEngineCountry
from policyengine_api.endpoints.policy import create_policy_reform, get_current_law_policy_id
from policyengine_api.data import PolicyEngineDatabase
from policyengine_api.economy_api.compare import compare_economic_outputs
from policyengine_api.economy_api.economy import compute_economy
from multiprocessing import Process

app = flask.Flask(__name__)

CORS(app)

uk = PolicyEngineCountry("policyengine_uk")
us = PolicyEngineCountry("policyengine_us")
countries = dict(uk=uk, us=us)

database = PolicyEngineDatabase(local=True)


@app.route("/", methods=[GET])
def home():
    return f"<h1>PolicyEngine compute API v{VERSION}</h1><p>Use this API to compute the impact of public policy on economies.</p>"


def set_economy_data(
    database: PolicyEngineDatabase, policy_id: int, country_id: str
) -> None:
    """
    Syncronously computes the economy data for a given policy and country.

    Args:
        database (PolicyEngineDatabase): The database.
        policy_id (int): The policy ID.
        country_id (str): The country ID. Currently supported countries are the UK and the US.
    """

    policy = database.get_policy(policy_id, country_id)["policy"]
    if policy is None:
        return flask.Response(f"Policy {policy_id} not found.", status=404)

    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)

    impact = compute_economy(country_id, policy_id)

    database.set_economy(impact, country_id, policy_id, True)


@app.route("/<country_id>/compare/<policy_id>", methods=[GET])
@app.route(
    "/<country_id>/compare/<policy_id>/<baseline_policy_id>", methods=[GET]
)
def score_policy_reform_against_baseline(
    country_id: str, policy_id: str, baseline_policy_id: str = None
) -> dict:
    """
    The /compare endpoint is designed for the PolicyEngine web app. It computes the impact of a policy reform
    on an economy, relative to a baseline policy.

    Args:
        country_id (str): The country ID. Currently supported countries are the UK and the US.
        policy_id (str): The policy ID.
        baseline_policy_id (str, optional): The baseline policy ID. Defaults to None (in which case the baseline is current law).

    Returns:
        dict: The results of the computation.
    """

    country = countries.get(country_id)
    if country is None:
        return flask.Response(f"Country {country_id} not found.", status=404)

    if baseline_policy_id is None:
        baseline_policy_id = get_current_law_policy_id(country_id)

    reform_impact = database.get_in_table

    if error:
        return {
            "status": "error",
        }

    if impact is not None and complete:
        return {
            "status": "complete",
            **impact["reform_impact_json"],
        }
    elif not complete:
        return {
            "status": "computing",
        }
    else:
        # Insert a new row into the database (designated as incomplete)
        database.set_reform_impact(
            None, country_id, baseline_policy_id, policy_id, False
        )

    Process(
        target=set_reform_impact_data,
        args=(database, baseline_policy_id, policy_id, country_id),
    ).start()

    return {"status": "computing"}


def set_reform_impact_data(
    database: PolicyEngineDatabase,
    baseline_policy_id: int,
    policy_id: int,
    country_id: str,
) -> None:
    """
    Syncronously computes the reform impact for a given policy and country.

    Args:
        database (PolicyEngineDatabase): The database.
        baseline_policy_id (int): The baseline policy ID.
        policy_id (int): The policy ID.
        country_id (str): The country ID. Currently supported countries are the UK and the US.
    """

    try:

        baseline_economy, baseline_stable = database.get_economy(
            country_id, baseline_policy_id
        )
        if baseline_economy is None:
            if baseline_stable:
                # The baseline economy is not in the database, and it hasn't been requested before.
                set_economy_data(database, baseline_policy_id, country_id)
                baseline_economy, baseline_stable = database.get_economy(
                    country_id, baseline_policy_id
                )

        reform_economy, reform_stable = database.get_economy(country_id, policy_id)
        if reform_economy is None:
            if reform_stable:
                # The reform economy is not in the database, and it hasn't been requested before.
                set_economy_data(database, policy_id, country_id)
                reform_economy, reform_stable = database.get_economy(
                    country_id, policy_id
                )

        impact = compare_economic_outputs(baseline_economy, reform_economy)

        database.set_reform_impact(
            impact, country_id, baseline_policy_id, policy_id, True
        )
    
    except Exception as e:
        database.set_reform_impact(
            None, country_id, baseline_policy_id, policy_id, True, error=True
        )
        pass

"""Example workflow loader - reuses existing database.save_workflow()"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Workflows folder at project root (parent of server/)
EXAMPLES_DIR = Path(__file__).parent.parent.parent / "workflows"


def get_example_workflows() -> List[Dict[str, Any]]:
    """Load all example workflow JSON files from disk."""
    examples = []
    if not EXAMPLES_DIR.exists():
        logger.warning(f"Examples directory not found: {EXAMPLES_DIR}")
        return examples

    for file in sorted(EXAMPLES_DIR.glob("*.json")):
        try:
            with open(file, encoding="utf-8") as f:
                workflow = json.load(f)
                workflow["_filename"] = file.name  # Track source
                examples.append(workflow)
                logger.debug(f"Loaded example: {file.name}")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load {file}: {e}")

    return examples


async def import_examples_for_user(database) -> int:
    """Import all examples using existing database.save_workflow().

    Dry-runs the workflow validator (services.workflow_validator) on each
    example before saving. Validation ERRORS skip the example (a broken
    example shipped on disk is a bug); WARNINGS are logged but allowed
    through — first-launch missing credentials are expected.

    Returns count of workflows imported.
    """
    from services.workflow_validator import validate_workflow

    examples = get_example_workflows()
    imported = 0

    for example in examples:
        # Use ID from JSON, prefixed with 'example_' for clarity
        workflow_id = f"example_{example.get('id', 'unknown')}"
        nodes = example.get("nodes", [])
        edges = example.get("edges", [])
        node_parameters = example.get("nodeParameters", {})

        # Pre-save validation. parameters_by_id from the JSON's
        # ``nodeParameters`` block lets INVALID_PARAM check see the
        # configured defaults instead of empty dicts.
        try:
            report = await validate_workflow(
                nodes=nodes, edges=edges,
                parameters_by_id=node_parameters,
            )
        except Exception as exc:
            logger.warning(
                "Skipping example %r: validator raised %s",
                example.get("name"), exc,
            )
            continue

        if report["errors"]:
            logger.warning(
                "Skipping example %r: %d validation errors %s",
                example.get("name"), len(report["errors"]),
                [iss.get("code") for iss in report["errors"]],
            )
            continue
        if report["warnings"]:
            # Expected on first launch — credentials not yet configured.
            logger.info(
                "Example %r has %d warnings (likely first-launch credential gaps)",
                example.get("name"), len(report["warnings"]),
            )

        # Reuse existing save_workflow method
        success = await database.save_workflow(
            workflow_id=workflow_id,
            name=example.get("name", "Example Workflow"),
            description=example.get("description"),
            data={"nodes": nodes, "edges": edges},
        )

        if success:
            imported += 1
            logger.info(f"Imported example: {example.get('name')}")

            # Save embedded nodeParameters if present
            for node_id, params in node_parameters.items():
                if params:
                    try:
                        await database.save_node_parameters(node_id, params)
                        logger.debug(f"Saved parameters for node {node_id}")
                    except Exception as e:
                        logger.error(f"Failed to save parameters for node {node_id}: {e}")

    return imported

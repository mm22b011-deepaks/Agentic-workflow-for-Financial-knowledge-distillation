"""Canvas metadata extends, and never duplicates, the executable CLI catalogue."""

from __future__ import annotations

import json
from pathlib import Path

from nowcast.cli_registry import catalogue
from nowcast.contracts import CanvasNode, CanvasRegistry, GraphDocument


def extension_path() -> Path:
    return Path(__file__).resolve().parents[2] / 'configs/workflow-canvas.json'


def canvas_registry() -> CanvasRegistry:
    source = extension_path()
    extension = json.loads(source.read_text())
    fields = json.loads((source.parent / 'io-fields.schema.json').read_text())['properties']
    commands = {item['id']: item for item in catalogue()}
    nodes = []
    for item in extension['nodes']:
        item['io']['example_fields'] = [
            {
                **field,
                'label': fields[field['key']]['title'],
                'description': fields[field['key']]['description'],
            }
            for field in item['io']['example_fields']
        ]
        command = commands.pop(item['id'], None)
        if item['id'] == 'extract-step':
            command = next(c for c in catalogue() if c['id'] == 'extract')
        nodes.append(CanvasNode.model_validate({**(command or {}), **item}))
    if commands:
        raise ValueError('CLI commands missing canvas nodes: ' + ','.join(commands))
    result = CanvasRegistry(
        nodes=nodes, edges=extension['edges'], graph_schema=GraphDocument.model_json_schema()
    )
    ids = {node.id for node in result.nodes}
    if len(ids) != len(result.nodes) or any(
        e.source not in ids or e.target not in ids for e in result.edges
    ):
        raise ValueError('invalid canvas ports')
    return result


def validate_ports(graph: GraphDocument) -> None:
    nodes = {node.id: node for node in canvas_registry().nodes}
    if any(point.id not in nodes for point in graph.nodes):
        raise ValueError('unknown graph node')
    seen = set()
    for edge in graph.edges:
        key = (edge.source, edge.target, edge.source_port, edge.target_port)
        if key in seen:
            raise ValueError('duplicate graph edge')
        seen.add(key)
        source = next(
            (
                port
                for port in nodes[edge.source].ports
                if port.id == (edge.source_port or 'out') and port.direction == 'out'
            ),
            None,
        )
        target = next(
            (
                port
                for port in nodes[edge.target].ports
                if port.id == (edge.target_port or 'in') and port.direction == 'in'
            ),
            None,
        )
        if source is None or target is None or source.kind != target.kind:
            raise ValueError('incompatible graph ports')

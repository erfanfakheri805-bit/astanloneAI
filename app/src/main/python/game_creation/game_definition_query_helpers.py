"""
Game Definition Query Helpers (Prompt 736, Section 7 - Professional Game Creation)
==================================================================================
Two tiny read-only yes/no helpers above the Prompt 735 query API.

    has_game_scene(game_definition, scene_id)        -> bool   (exactly `lookup_game_scene(...).found`)
    has_game_scene_bundle(game_definition, scene_id) -> bool   (exactly `lookup_game_scene_bundle(...).found`)

Each helper delegates directly to the matching public query function and returns the `found` field of its result unchanged. Everything else is
inherited from Prompt 735: exact matching only (no trimming, case-folding, normalization or coercion); an invalid `game_definition` or a
`scene_id` that is not exactly a `str` simply gives `False` (the query result's `found` is False); nothing is raised, validated, copied or
mutated; registry internals are never touched and no list is scanned. The module is stateless and deterministic, and is not wired into
`process_input()`, Core, the Planner or the Agent Loop.
"""

from .game_definition_queries import lookup_game_scene, lookup_game_scene_bundle


def has_game_scene(game_definition, scene_id):
    """True only when `lookup_game_scene(game_definition, scene_id)` found the scene; False for a miss or any invalid argument."""
    return lookup_game_scene(game_definition, scene_id).found


def has_game_scene_bundle(game_definition, scene_id):
    """True only when `lookup_game_scene_bundle(game_definition, scene_id)` found the bundle; False for a miss or any invalid argument."""
    return lookup_game_scene_bundle(game_definition, scene_id).found

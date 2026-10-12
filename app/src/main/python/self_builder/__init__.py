"""
Self-Builder - controlled internal capability builder
=====================================================
A real, bounded, local-only mechanism by which the application adds a new
*supported* capability to itself, from an ordinary Persian request, without any
developer or external AI service:

    request -> analyze -> check capabilities -> identify gap -> change plan ->
    generate (allowed files only) -> validate -> test -> [analyze failure ->
    safe repair -> retest] -> checkpoint -> apply -> persist -> register ->
    version -> audit            (rollback restores the previous verified version)

"Supported" means: an archetype with a reviewed template exists
(`policy.SUPPORTED_ARCHETYPES`: unit conversion, formula, text tool). There is
no code-generating model here; a request outside the archetypes is answered
honestly instead of being guessed at (see docs/self_builder_final_exit.md).

Importing this package has no side effects: nothing is created on disk until a
build (or an existing registry) is actually used - see `service.get_service`.
"""

__all__ = ["policy", "errors", "service"]

# Public / Private Boundary

Goal Harness is designed to be public, but most useful goal evidence is not.

## Public

These are safe to keep in the public repository:

- schemas,
- runtime directory conventions,
- generic CLI code,
- adapter lifecycle rules,
- validation commands,
- sanitized examples,
- high-level design notes.

## Private

These should stay in project-local ignored files:

- local absolute paths,
- internal repository names,
- raw logs and metrics,
- task ids,
- document links,
- credentials and tokens,
- person or team names from private work,
- active goal state that reveals current user context.

## Practical Rule

The public repo should answer: "How does a goal harness work?"

The project repo should answer: "What is this specific goal currently doing?"

The runtime root should answer: "What happened in recent goal ticks?"

# Layered Product Development

Layered development activates only when the user explicitly asks to use layered development for a complex product task.

The product architecture dimensions are:

- `presentation`: user-visible experience, interaction, client state and accessibility.
- `protocol`: API, authorization, validation, business rules, state transitions and integration semantics.
- `data`: schema, persistence, queries, transactions, migrations, retention and recovery.

Each layer contract must answer four questions before implementation:

1. What final outcome must this layer deliver and how is it observed?
2. What is in scope, out of scope, and which interfaces connect other layers?
3. Which partial results must not be accepted as completion?
4. What must be explored, who implements it, who audits independently, and what evidence is required?

Do not force a fixed presentation -> protocol -> data sequence. Define interfaces first, group work into product-capability slices, and schedule layer tasks by real dependencies. A layer can be `not_applicable` only with an explicit reason.

Security, privacy, performance, observability, deployment and end-to-end verification are cross-layer gates. Passing one layer does not satisfy the product-level acceptance gate.

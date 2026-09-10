# V4 code-path visual specification

## Adaptive execution and evidence reuse

Choose the interaction pattern from the user's request and the existing project state:

- **Autonomous completion:** use when the user asks for an end-to-end result, will be unavailable, or explicitly says not to pause. Continue through research, decomposition, focused pages, master integration, and review. Pause only for a material unresolved choice that would substantially change the architecture or exceed the authorized scope.
- **Checkpointed collaboration:** use when the user wants to shape the hierarchy or visual density interactively. Present checkpoints at decisions with high rework cost—normally the evidence/hierarchy contract and stable focused-module previews—not after every operator.
- **Direct single-canvas:** use for a bounded one-level diagram or a targeted visual revision with no expected master composition.

Infer the mode when the user's wording is clear. Do not ask a redundant mode question after instructions such as “finish it,” “show me each level,” or “only change the layout.” Ask one concise question only if the choice is genuinely ambiguous and would materially affect scope or rework. A later user instruction may switch modes without restarting completed work.

Classify evidence state before research:

- **Cold start:** no usable manifest or version-matched local evidence exists. Perform the full evidence pass.
- **Warm resume:** a manifest and pinned sources cover the requested model and execution mode. Load them before any network research and continue from the last consistent contract.
- **Targeted revision:** the request changes presentation or a bounded module. Reuse unaffected evidence and validate only claims touched by the change.

Prefer durable local evidence over conversational memory: a project manifest, locally saved reports/configs, and a source checkout pinned to a commit or release. Record source URL or repository path, model/checkpoint identifier, revision or commit when available, retrieval date, and the claims each source supports. Model memory may suggest where to look but is never evidence and must not silently fill manifest gaps.

Do not repeat broad web research on every interaction. Refresh only when at least one invalidation condition applies:

- the requested model, checkpoint, revision, modality, or execution mode changed;
- the relevant claim is absent, inferred, unknown, or conflicting;
- local evidence lacks a reproducible version identifier or no longer matches the current source;
- the user requests current/latest information;
- new code or configuration contradicts the manifest;
- the requested expansion crosses into a module not covered by existing evidence.

For layout-only edits, reuse the existing topology contract without architectural research. For a new module, run a targeted evidence pass and update only its dependent shapes and parent mappings. When evidence is invalidated, revise the evidence record and shape ledger first, then the topology contract, then every affected focused and master view.

## Output views

Treat interaction mode and output view as separate choices. A user may request autonomous completion of any view, or checkpointed collaboration for any view.

- **Hierarchy master:** emphasizes containment, repetition levels, and parent-to-child expansion. Use large hollow hierarchy arrows and focused component pages. It answers “what is the model made of and where does each implementation belong?”
- **End-to-end dependency/dataflow master:** emphasizes a continuous producer-to-consumer path from every input to every requested output. Put tensor shapes on edges, show side-branch injection and state/cache dependencies, and expand each unique implementation once. Fold only structurally identical repetition. It answers “how does data move and change shape?” Read [end-to-end-dataflow.md](end-to-end-dataflow.md) when producing this view.
- **Paired delivery:** produces both masters from one evidence record, shape ledger, symbol dictionary, and topology source. Use when both conceptual navigation and executable data tracing matter; do not maintain two independent architectures.

If a new diagram request does not select a view and the distinction materially affects the deliverable, ask the user to choose after a one-sentence explanation of the three options. Do not ask when the wording already says “hierarchy,” “from input to output,” “complete dataflow,” “both,” or equivalent. A warm resume inherits the existing output view unless the user requests another.

## Evidence gate and shape derivation

Do not begin detailed topology or geometry from a marketing overview alone. First establish a version-matched evidence base. Prefer sources in this order, while recognizing that each answers a different question:

1. canonical executable model source and its forward path for actual operator order, branches, and state updates;
2. official checkpoint configuration or model metadata for dimensions, counts, cadence, and feature flags;
3. official technical report, paper, and architecture figures for intended semantics and named modules;
4. explicitly inherited predecessor source or reports for unchanged internals;
5. maintained inference-framework implementations as supporting evidence for deployed execution;
6. third-party analysis only as a lead to verify, not as sole authority for a material claim.

Match sources to the exact model, checkpoint, revision, and execution mode whenever possible. Source priority is not a mechanical winner: a report may describe intent while code implements a particular revision, and an inference backend may fuse or rewrite the graph. When sources disagree, check version alignment and record the conflict instead of silently choosing the most convenient topology.

Maintain a compact evidence record for every material claim. Use these statuses:

- `code/config confirmed`: supported by version-matched executable code or configuration;
- `report confirmed`: stated by an official report or figure but not yet located in executable code;
- `inherited`: traced to a named predecessor/version and not contradicted by current evidence;
- `inferred`: derived from surrounding dimensions, conventions, or incomplete code;
- `conflicting`: credible sources disagree;
- `unknown`: evidence is insufficient.

An inherited claim must name the predecessor and the evidence that the current model retains it. Never render `inferred`, `conflicting`, or `unknown` behavior as an unqualified established execution path. Mark it visibly when it must appear, isolate alternatives when they materially change the graph, or keep it in the evidence notes until resolved.

Derive a shape ledger before the topology contract. For each relevant edge or state, record:

- producer and consumer;
- input and output shape with symbol definitions;
- hidden, projection, expert, vocabulary, and intermediate dimensions;
- query/key/value head counts and head dimension where applicable;
- reshape, transpose, split, concatenate, gather, broadcast, and head-replication operations;
- repeated unit boundary, cadence, and count;
- branch source, merge/injection destination, and broadcast rules;
- cache, recurrent state, convolution state, or auxiliary state shape and lifetime;
- evidence source and status for the value or derivation.

Check dimensional closure across every split, merge, residual update, and repeated boundary. A missing dimension may remain symbolic; an unsupported numeric value must not be guessed merely to make the diagram look complete.

### Operator nodes versus tensor labels

Use boxes for executable modules and operators, not for every program variable. Put short-lived tensors and their shapes on producer-to-consumer edges by default. A tensor node is justified only when it is a model or subgraph interface, a persistent cache/recurrent state, a repetition boundary, a necessary multi-consumer fan-out checkpoint, or an independently meaningful stored artifact. Names such as `Rin`, `Rmid`, `Rout`, `x`, and `hidden_states` are not sufficient reasons by themselves. At a repeated-layer boundary, retaining `R0`/`Rlast` may be useful; the same convention does not justify boxing every intra-layer residual.

Before geometry, maintain a **node-semantic ledger** in addition to the shape ledger. For every visible box, arithmetic symbol, cache/state, and named interface, record its visual identifier, visual class, source-backed semantic referent, evidence status, and whether it is executable, persistent, a declared boundary, or a pure junction. A rectangular/operator/interface symbol must map to a real module, operation, persistent artifact, or declared model/subgraph boundary. Do not use a source name alone as evidence that a node exists.

Use a small neutral junction (or an edge label) for route-only fan-in/fan-out. It may be named only by the tensors it joins, never with terms such as `interface`, `dispatch`, `adapter`, `merge`, or `stage` unless that operation/boundary exists in evidence. The “necessary multi-consumer fan-out checkpoint” exception applies only when the checkpoint is itself a meaningful stored/interface artifact or intentionally declared abstraction—not when a large box merely makes wires easier to route. A junction is not an operator, must not use an operation-class fill, and should not carry explanatory prose.

Audit every arithmetic node for dimensional closure. When operands have different ranks, show the actual `reshape`, `unflatten`, `unsqueeze`, `repeat`, or broadcast semantics before or inside the operator; never rely on a bare `×` or `+` symbol to imply them. For a common multi-stream residual injection, a shared output `y [...,D]` and stream gates `α [...,H]` do not mean that `y` is split into `H` pieces. Render the broadcast outer product explicitly:

`y.unsqueeze(-2) [...,1,D] × α.unsqueeze(-1) [...,H,1] → ΔR [...,H,D]`.

If the executable implementation stores the multi-stream residual flattened, label the equivalence at the interface or edge, for example `[...,H·D] ≡ [...,H,D]`, and distinguish conceptual shape from physical storage without adding redundant tensor boxes.

For complex or multi-session work, preserve a compact evidence/topology manifest beside the diagram sources. It should contain the level tree, source locations and version identifiers, claim/status table, shape ledger, unresolved ambiguities, topology-contract revisions, and focused-page-to-master parent mappings. Update the evidence record and shape ledger first when new facts arrive, then the topology contract, then focused and master drawings. This order prevents geometry from becoming the accidental source of truth.

## Pre-drawing topology contract

Draft the architecture in plain text or ASCII before deciding coordinates. This is an intermediate representation, not a deliverable unless requested. It should make the following facts unambiguous:

- one reading direction for the main tensor path; macro backbones may choose the clearest direction, while every operator/implementation-detail path is vertical bottom-to-top;
- ordered modules and tensor shapes between them;
- the exact boundary and count of every repeated unit;
- fixed layer cadence versus genuine runtime branching;
- each side branch's source, destination, and injection point;
- which parent modules will be expanded at the next level.

Prefer one short contract per main level. For example, keep the model stack (`input adapter → repeated backbone → output head`) separate from a layer contract (`normalize → mixer → residual update → feed-forward`). If a single ASCII box contains both, label the inner portion explicitly as an expansion; otherwise split it before drawing. This prevents a repeated backbone from being mistaken for one layer and prevents any fixed layer cadence from becoming an `if` flowchart.

Treat the confirmed contract as the topology source of truth during layout. Visual styling may move nodes, but it must not change order, repetition scope, shapes, or branch attachment. If evidence later changes the architecture, update the contract first and then revise the diagram.

### Leaf-module granularity

Before drawing a detailed leaf module, write a branch ledger with one row per semantic output: source tensor, parameterized operator, output shape, normalization/reshape/cache treatment, and immediate consumer. Two branches must remain visually separate when any of the following differs: learned parameter set, output rank or dimension, post-processing, state/cache behavior, broadcast rule, or consumer. A shared source is not a reason to merge branches.

Apply granularity consistently among sibling modules presented at the same declared level. If one Level-2 mixer exposes independent Q/K/V projections and shapes, another Level-2 module must not collapse independent K/V projections into one box merely to save space. Either expand the latter to matching operator-level detail or explicitly classify it as a compact overview at a different level. A packed parameterized projection may remain one node only when its packed output, explicit split, and independent branches are shown. A fused execution call never erases its member logical nodes from `operator-detail`; record fusion separately. An intentionally compact parent boundary is legal only when its hidden distinctions are expanded elsewhere and linked explicitly.

## Hierarchy plan and master canvas

Before drawing individual pages, write a compact **hierarchy contract**. It has two graphs, which must never be silently conflated:

1. **Containment/ownership tree:** answers “what owns this definition?” Every node has one containment parent. It may contain model components, layer templates, branch definitions, and a canonical implementation library; it never gives a shared implementation two parents.
2. **Call-and-reuse DAG:** answers “which template/branch invokes this definition?” A reusable GR, MoE, kernel, or adapter is defined once and may have many typed caller references. A call/reuse relation is not containment and must not be disguised as one.

For every planned level, maintain an expansion registry with: `identifier`, `semantic definition`, `containment parent`, `callers`, `evidence status`, `detail target`, and `state` (`expanded`, `intentionally folded`, or `not yet expanded`). Distinguish repeated instances from deeper detail; for example, `Hybrid Block ×12 → {Local-Mixer template, Global-Mixer template}` is a hierarchy expansion, while `[Local, Local, Local, Global] ×12` is repetition. A lower visual row, shared color, or proximity does not create a parent-child relation.

Use level labels consistently as **detail granularity**, not literal containment depth: Level 0 is model/component composition; Level 1 is representative repeated templates or major branch compositions; Level 2 is the internal mathematical/operator definition of one named component; Level 3 is a detail implementation of one specific Level-2 definition, such as execution modes or kernel/state paths. A Level-3 region must have an explicit expansion mapping to its actual Level-2 definition, normally shown by a large hollow arrow. Do not require every Level-2 component to have Level 3: record unexpanded children in the registry instead of manufacturing symmetry.

A hierarchy master may therefore use a visually centralized backbone, adjacent Level-1 templates, and a shared bottom/side Level-2 implementation band. This is a valid level-of-detail layout, not a failure to draw a tree, when it answers “what is expanded next?” clearly. Preserve the ownership tree and caller DAG in the contract/manifest; use arrows, labels, or a compact expansion index to disambiguate a child expansion where the visual layout alone could be read as containment. Do not force shared implementations beneath one caller merely to make the canvas tree-shaped.

### Spatial ownership invariant

Treat proximity, vertical continuation, nesting, alignment, and a reserved arrow corridor as semantic signals. The viewer must not need the manifest to correct a false parent-child relationship suggested by the canvas.

Before assigning coordinates, classify every relation as exactly one of:

- `expand/owns`: actual definition to its internal detail; use the large hollow hierarchy arrow;
- `uses/calls/injects/reuses`: a non-owning dependency or call-site; use a thin, lightweight, explicitly typed relation that cannot be mistaken for expansion;
- `tensor/state flow`: executable producer-to-consumer data movement; use the normal solid orthogonal arrow;
- `proximity only`: no semantic relation; keep enough gutter and avoid parent-child alignment cues.

Build a parent-anchor table containing `child region`, `semantic parent node`, `relationship type`, `attachment mode`, `physical attachment`, `attachment side/corridor`, `anchor label`, and `visual zone`. The semantic parent must be the actual definition, never a level header, placeholder, convenient call-site, or geometrically nearby module. The physical tail may touch that node or a registered boundary egress of its direct owner/ownership ancestor. A region egress is only a routing surface: it does not become another parent, and its visible label must name the semantic parent. When the actual parent is already present on the master, do not introduce a proxy parent merely to obtain convenient geometry.

Place model-level side branches as siblings in a common model-branch expansion zone when practical. Examples include auxiliary embeddings, prediction heads, and modality towers. A model-level branch must not sit inside or directly below a layer-internal module's expansion column unless a clear gutter and an explicit parent-originating expansion route remove that implication. A call-site inside a repeated layer may point to a branch implementation with a typed `uses` or `injects` relation, but it does not own that implementation.

Run a spatial-semantics audit before styling and again on the exported full-canvas preview:

1. For each child region, identify the parent a new viewer would infer from placement alone.
2. Compare that inferred parent with the ownership tree and parent-anchor table.
3. Verify that every large hollow arrow connects an `expand/owns` pair.
4. Verify that every call, injection, or reuse edge is visibly distinct and labeled.
5. Verify that same-level model branches read as siblings rather than descendants of whichever detailed region happens to be nearest.

Any mismatch is a topology failure, not a cosmetic preference. Reflow the canvas, move the child into the correct sibling zone, or reroute from the registered parent-node/owner-region attachment; a note in the manifest is not sufficient repair.

Sketch the master canvas while the hierarchy is still small. Keep the model-level backbone near the visual center, reserve outward regions for deeper expansions, and reserve unobstructed corridors for hierarchy arrows. The symbol sketch should show titled dashed regions, approximate node stacks, tensor-flow direction, and branch routes; it need not contain final colors or typography.

Treat the canvas as a topology-dependent workspace, not a fixed template. The main backbone does not have to start in the upper-left. An auxiliary prediction head may sit above the backbone, a modality tower may sit beside it, and implementation bands may wrap around the central structure when this shortens expansion routes and preserves sibling relationships. Reposition top-level components before accepting long or ambiguous hierarchy arrows; enlarge width or height only after testing a more coherent composition.

Freedom at the master-canvas level does not apply inside an execution region. Lay every `module-summary`, `operator-detail`, and `implementation-detail` sequence vertically from bottom to top. Use adjacent vertical lanes for fan-out and side positions for state/cache; do not rotate or diagonally stretch an operator chain to fill leftover master-canvas space. Shared prefixes and suffixes form one compact trunk. An individual branch may leave and rejoin that trunk laterally, but adjacent sequence steps must not cross several node widths merely because the outer region or canvas is wide. Compute the visible region from this compact execution envelope before adding hierarchy relationships; hierarchy corridors remain outside it and may not be created by pulling lanes toward opposite borders.

A hierarchy arrow is a route, not necessarily a standalone straight shape. Use a straight hollow block arrow when the registered physical attachment and child have a direct unobstructed corridor. Otherwise use a wide white hollow orthogonal arrow with a dark outline and one or more deliberate 90-degree bends. Its tail must touch either the semantic parent node or its registered owning-region boundary egress, and its tip must touch the owned child-region boundary. An owner-region egress must retain an unambiguous visible anchor label naming the semantic parent. Keep the shaft visually much heavier than tensor flow, maintain a constant apparent width through bends, and reserve a clear elbow radius or square elbow so the route does not resemble several unrelated line segments. Label the route once; do not repeat the full mapping at every segment.

Treat the selected hierarchy-arrow language as a visual-role lock. If the user or reference chooses large block arrows, do not silently replace them with long stroked edge routes merely because the existing row layout lacks a corridor. First recompose the canvas: move auxiliary heads above the backbone, move model-level branches beside it, stagger detailed levels, or place a child on another side of its parent. A long double-stroked polyline that reads as a cable is not an acceptable substitute for a block arrow, even when its outline is technically hollow. Prefer a short straight block arrow whose body substantially fills the parent/child gutter. Use a bent hollow block route only when the reference uses that language or a compact reflow still cannot create a direct corridor; keep it local and visually monolithic.

For a straight block arrow, treat length-to-thickness ratio above `6.0` as a blocking cable-like geometry by default. Before accepting an exception, demonstrate that north, south, east, and west child placements were considered and that a named obstacle prevents every shorter direct corridor. Uniformly assigning every child to the same side is not evidence of such a constraint.

Choose hierarchy geometry in this order:

1. reflow parent and child regions to create a short direct corridor;
2. move auxiliary top-level branches above or beside the backbone, and stagger deeper child bands, when that frees a clearer child zone;
3. enlarge or rebalance the canvas when it converts a long route into a short block-arrow gutter without harming the declared viewing scale;
4. use a one- or two-bend hollow orthogonal block route only when the chosen visual language permits it and the route remains compact rather than cable-like.

Never change ownership, place a child under a convenient unrelated parent, or replace a precise bent route with a vague nearby straight arrow merely because the current generator supports only straight block-arrow nodes. Extend the drawing primitive or draw the route explicitly.

Maintain a region ledger while composing the master. For every titled region, record its identifier, parent, bounding box, and z/render order. Use the ledger to distinguish legal parent-child containment from illegal sibling overlap. Before export and after every integration, detect top-level sibling intersections, same-parent nested sibling intersections, and later-rendered opaque regions that cover earlier titles, boundaries, nodes, edges, or hierarchy arrows. Do not treat a successful text-fit check as evidence that the composed layout is collision-free.

Leave a visible gutter between siblings whose projections overlap on the other axis. As a practical native-canvas starting point, use 20–40 px and increase it when fit-to-width scaling makes dashed borders merge visually. Merely making two opaque region bounds coincide is not sufficient. Also reserve separate header and hierarchy-arrow corridors so a region title and its first execution node cannot be covered by an incoming expansion arrow.

Focused level pages and the master diagram must derive from the same topology contracts. Compose a master structurally rather than stitching exported pages:

- use one title, one Legend, and one symbol definition area;
- remove child-page parent proxies when the actual parent is present on the master;
- point a large hollow arrow from the actual parent/canonical definition, or from its registered owning-region boundary egress, to the child region when that expansion is visually local; retain the semantic parent in the expansion registry and use an unambiguous anchor label or compact expansion index instead of manufacturing false containment;
- label expansion arrows as `expand` only when they connect a parent definition/call-site to its owned detail; render shared callers as visibly different, lightweight reuse relations, and include a nearby canonical-owner label when placement could otherwise imply false parenthood;
- preserve the child subgraph's internal tensor order and shapes;
- enlarge or reflow the canvas instead of shrinking detailed blocks until labels become unreadable;
- keep focused level files for editing and validation even when the master becomes the primary deliverable.

## Working modes and incremental synchronization

Use a direct single-canvas workflow when the requested diagram has one level, few branches, and no expected master composition. Do not manufacture focused pages merely to satisfy a process.

For a dense multi-level deliverable, use a master-first/focused-detail workflow:

1. Create the hierarchy tree, topology contracts, and a low-fidelity master skeleton before detailed geometry.
2. Reserve external master-canvas slots and hierarchy-arrow corridors for all known expansions, even if those child slots are initially empty; do not reserve those corridors by inflating an execution owner region.
3. Build a focused page for a module when its internal branches, states, shapes, or execution variants need detail-scale validation.
4. After the focused module is structurally stable, integrate it into the master immediately or at the next natural composition checkpoint. Do not wait until every focused page is finished before testing composition.
5. Reflow or enlarge the master as it grows. Do not compress a validated child until its labels and branch ownership become ambiguous.
6. Run a cross-view drift check after each integration: operator order, repetition scope, edge shapes, branch attachment, cache/state ownership, and expansion target must agree.

The topology source of truth may be compact text contracts, a structured graph description, or reusable generator data. When a generator is available, focused pages and master regions should reuse stable module identifiers and definitions instead of duplicating geometry by hand. When no generator is available, update the contract first and use it as the reconciliation checklist for both views.

Human review is most valuable at decisions that materially change hierarchy, evidence interpretation, or visual density. Do not require approval after every block when the topology is established and the user asked for autonomous completion; still expose focused previews when they materially reduce rework.

## Canonical Draw.io rendering

When the editable deliverable is Draw.io, use `.drawio` as the canonical visual artifact. The in-memory topology or an independently generated SVG may share the same node data without sharing Draw.io's port selection, orthogonal routing, label placement, text wrapping, font fallback, or shape geometry.

For every explicitly routed edge, serialize both the route and its attachment constraints. In mxGraph XML, intermediate `mxPoint` waypoints do not preserve the first and last absolute points: constrain the source and target with `exitX`, `exitY`, `entryX`, and `entryY` (or an equivalent fixed-port mechanism). A two-point route without fixed ports is not explicit; diagrams.net may silently reconnect it center-to-center and route through an intervening state or module.

Use this acceptance order:

1. generate and structurally audit the `.drawio` XML;
2. verify declared endpoints survived as Draw.io port constraints;
3. export PNG/SVG with diagrams.net/Draw.io;
4. inspect the full-canvas export and required detail crops;
5. reopen the editable file when practical and verify representative routes remain stable after selection or movement.

An independent SVG writer is useful for rapid iteration but is not a visual oracle for Draw.io. Never claim Draw.io visual acceptance from that preview alone. If diagrams.net/Draw.io export is unavailable in the environment, state `Draw.io structural audit passed; Draw.io-rendered visual audit pending` and give the user the editable artifact for the remaining check.

## Presentation scale, typography, and collision budget

Design for a declared viewing profile rather than native-canvas pixels alone. Record the master canvas width, target viewport or print size, fit scale, detail inspection scale, and whether every micro-label or only overview labels must be readable at full view. If the user does not specify a profile, use these defaults:

- master overview: fit-to-width at 2560 px;
- primary reading frame: the model backbone, one focused level, or another semantically complete region fitted into a 1440–1600 px-wide screen without browser/image upscaling;
- detailed reading: 100% scale or a 1440–1600 px crop;
- editable delivery: vector or draw.io source so deeper zoom remains lossless.

Calibrate typography against the primary reading frame first. A useful reference-derived baseline is a native block font around 27 and a hierarchy-arrow/relationship-label font around 20 when the region is displayed at about 0.6 scale; these become approximately 16 and 12 apparent pixels. Treat those native values as a calibration point, not a mandate: compute `native size = desired apparent size / projected fit scale`, then round to a small role palette. Do not inherit 12 px editor defaults for architecturally important blocks merely because they fit. Conversely, do not apply 27 px mechanically to a much narrower or unscaled detail page.

Use a compact role palette rather than independent per-node values. Unless the supplied reference establishes another hierarchy, start with:

- ordinary one-line block label: 16–18 px apparent in the primary reading frame;
- major block/backbone label: 17–20 px apparent;
- hierarchy-arrow or typed relationship label: 12–14 px apparent;
- tensor-shape/edge label: 10–12 px apparent, increased when it is essential to first-pass reading;
- region title: at least 14–16 px apparent in its intended reading frame.

Equivalent sibling nodes use the same font size, line height, padding, and minimum height. Change size only for a declared semantic role, not because one label happens to be shorter. Prefer shortening or wrapping a long label, then widening the whole sibling family if necessary; do not shrink one node's text independently.

For a raster or fit-to-width preview, estimate `apparent size = native size × target width / canvas width`. Uniformly enlarging fonts, nodes, and the canvas does not improve apparent size because the fit scale shrinks by the same factor. Improve readability by reducing unused width, reflowing regions, removing duplicated prose, or changing the overview/detail contract before globally scaling geometry.

Use role-based apparent-size floors at the declared viewing scale. These are acceptance floors, not mandatory native font values:

| Role | Master overview | Detail view |
|---|---:|---:|
| Diagram title | 18 px | 18 px |
| Level/subgraph title | 11 px | 14 px |
| Hierarchy-arrow label | 10 px | 12 px |
| Major backbone node | 9 px | 13 px |
| Ordinary operator label | may require zoom | 12 px |
| Tensor-shape / edge label | may require zoom | 10 px |
| Legend / symbol definition | 9 px | 11 px |

The master full view must expose hierarchy, ownership, major backbone nodes, and expansion relationships. It need not expose every operator or tensor shape unless the user explicitly requires all-text-at-fit readability. When that requirement would exceed the viewport's information budget, reflow or provide a paired readable overview and zoomable detailed master; do not silently shrink labels.

Use one reference-compatible sans-serif family with all required glyphs. Prefer the supplied reference font; otherwise choose an installed family with reliable Latin, math-symbol, and CJK coverage. Use weight and size—not multiple font families—to express hierarchy. Verify SVG/PDF/draw.io export with the actual font; a fallback font may change wrapping and invalidate layout.

Build geometry from text outward:

1. Measure or conservatively estimate each label at the chosen family, size, and line height.
2. Keep ordinary operator text concise, normally one title plus at most two short detail lines. Move explanatory prose to evidence notes or split a real composite operation instead of packing a card.
3. Size the node for the wrapped text plus consistent padding. Never use font shrinking to make a fixed node fit.
4. Reflow the local subgraph after node growth, preserving dedicated branch and edge-label corridors.
5. Reflow the master after the focused region is stable. Enlarging the outer canvas is allowed only if the target apparent sizes still pass.

### Node padding and compact dependency spacing

Express spacing relative to the active text size so the style survives canvas scaling. For a compact one-line operator block, start with horizontal padding of `0.8–1.2em` per side and vertical padding of `0.45–0.7em` above and below the measured line box. This normally yields a total one-line block height around `1.9–2.4em`. Multi-line blocks keep the same outer padding and use a line height around `1.15–1.3em`; add space by growing the node, never by shrinking the text.

Visible nodes are content-hugging semantic objects, not routing rails. Compute a node's natural width from the measured longest line plus its horizontal padding. Centering a node on a lane does not require stretching it to the lane width. Keep the following concerns separate:

- **node width:** label content, icon/operator geometry, and padding;
- **lane width:** room for parallel dependencies and sibling alignment;
- **port placement:** attachment points on the compact node boundary;
- **routing corridor:** empty canvas reserved for bends, labels, and state/cache edges; hierarchy arrows use a separate external relationship layer and never determine ordinary node or execution-region width.

Do not widen an ordinary operator merely to span a column, make two execution modes look symmetric, align remote side-state ports, or avoid calculating a route. Use explicit ports, short lead segments, a visible semantic junction, or an invisible layout grid instead. Equal-width siblings are acceptable when comparison is meaningful, but derive the family width from the longest natural sibling plus common padding—not from the containing region. A genuinely wide box needs a semantic reason, such as a multi-column operation, a labeled repeated boundary, or a deliberately emphasized major module.

Audit horizontal content occupancy after rendering: `occupancy = rendered longest-line width / inner node width`. For ordinary one-line blocks, roughly `55–85%` is a useful content-hugging range. Values below about `40%` require a recorded reason or redesign; this threshold is a review trigger rather than a license to compress long labels into cramped boxes. For multi-line blocks, inspect the longest meaningful line and the overall text block, not a short subtitle. Never compensate for an over-wide node by leaving the font small.

Use the smallest dependency-aware gap that preserves all required visual channels. Between consecutive nodes on a simple straight tensor spine, begin near `0.8–1.4` one-line node heights, then reserve additional space only for an edge label, arrowhead, branch merge, or crossing-free orthogonal turn. Between sibling lanes, begin near `1–1.5em` beyond the widest labels and arrowheads. Between titled regions, use the region-gutter rules rather than operator gaps. These are starting ranges: compact further when the route remains unambiguous, and expand locally when content or dependency geometry requires it.

Judge compactness structurally, not by uniform distances. Nodes with a direct dependency should read as a group; unrelated branches should retain enough gutter to avoid false ownership. Avoid both large empty vertical runs on a simple spine and tight packing that forces labels onto arrowheads or causes ports to share collinear segments. After routing, make a second compaction pass: remove unused whitespace, shorten avoidable detours, and equalize analogous gaps, while preserving parent-child zones, edge-label corridors, and the declared apparent font sizes.

At detail scale, leave visible clearance around every text box. Edge-label backgrounds may be white or match the canvas, but must not hide unrelated paths. Reject clipping, ellipsis, unintended line breaks, labels touching boundaries, labels sitting on arrowheads, and parallel edges whose labels cannot be assigned unambiguously. Run a collision pass after font substitution and after every focused-to-master integration. That pass must include both local text geometry and the region ledger: sibling bounding boxes, minimum gutters, header corridors, hierarchy-arrow corridors, and opaque render-order occlusion.

The collision pass must also compare every visible node bounding box against its peers; text-fit and region-fit checks do not detect node-on-node overlap. Treat arithmetic symbols, state/cache shapes, hierarchy arrows, and ordinary operator boxes alike unless one is intentionally contained and that containment is part of the notation.

Audit edge ports and segments separately from node geometry. An incoming edge and an outgoing edge must not meet the same side of a node on the same collinear segment: the arrowhead can be hidden by the departing line and reverse the apparent direction. Give them distinct ports or sides with visible separation. Multiple outgoing edges may share a trunk only when a visible junction establishes fan-out and all arrows travel in the same direction; otherwise split them immediately into separate lanes. Reject exact or near-exact opposite-direction segment overlap and any shared segment whose ownership or direction cannot be identified at detail scale.

Run a pairwise edge/edge geometry audit over every orthogonal segment, independently of node collision checks. Reject a T-intersection without a semantic junction and any positive-length collinear overlap unless the shared trunk is explicitly declared as a same-source fan-out rail and remains directionally clear. Prefer eliminating unrelated interior crossings through ports, lane order, or local reflow. If one isolated perpendicular crossing is unavoidable, render a small arc line jump on exactly one declared upper edge so the non-connection is unmistakable; bind the pair, jumper, size, and reason through layout and manifest, and verify the curve in the official SVG. A line jump may not sit near an endpoint, bend, arrowhead, or label, and several jumps on one edge are a reflow signal rather than a general routing technique. Do not automatically allow every pair with the same source: that exception hides accidental shared routes. Keep every rail, junction, and line-jump declaration in the diagram source or routing ledger so the audit has a narrow, reviewable contract. Separately audit that every visible non-junction node has a semantic-ledger mapping and that no pure junction is rendered as a module-like box.

Optimize local routing before adding detours. Try, in order, exchanging free source or target ports, ordering parallel lanes to match their destinations, shifting a corridor, and reordering or moving sibling nodes without changing topology. Prefer the non-crossing orthogonal route with the fewest bends and shortest Manhattan length. A generator should report conspicuous route inflation (for example, several bends and a path many times longer than the endpoint Manhattan distance) for review; obstacles may justify it, but the exception must be explicit. Shared-source branches should either split immediately into independent lanes or use one visible junction, not form an unlabeled bundle of partially overlapping segments.

For every explicitly routed edge, verify geometrically that its first point lies on the declared source boundary and its last point lies on the declared target boundary. A valid source/target identifier is not enough: stale waypoints after moving or resizing a node can leave a visible gap. Check every orthogonal segment against all unrelated node interiors as well. Route external branches through reserved corridors and into a free side of the target; never let a line pass behind an unrelated box and appear to originate from it.

Record the geometry audit scope in the delivery note: node/node collisions, endpoint attachment, edge/node crossings, edge/edge crossings, collinear overlaps, permitted fan-out rails or junctions, and route-inflation review. A generic “audit passed” is insufficient because these checks catch different failure classes.

Scale non-text elements with the same viewing profile. Tensor-flow lines should remain visually lighter than hierarchy arrows; dashed boundaries must remain visible but subordinate; arrowheads must remain distinguishable from junctions; arithmetic circles must still read as operators. As a starting range at detail scale, use roughly 1.5–2 px tensor lines, 1–1.5 px boundaries, and 2–3 px hierarchy outlines, then compensate for the fit scale. Preserve high text/background contrast and do not rely on color alone to distinguish roles.

If a readability floor fails, repair in this order:

1. remove accidental whitespace and duplicated annotations;
2. shorten labels without deleting architectural facts;
3. widen or reflow nodes and local subgraphs;
4. rebalance the master aspect ratio and expansion placement;
5. revise the full-view/detail-view contract or add a readable overview companion.

Do not solve a readability failure by reducing font size, collapsing distinct branches, hiding required tensor shapes, or making all strokes equally heavy.

## Multi-agent execution and independent topology review

General multi-agent work is an optional scaling technique, not a prerequisite for this style. The strict cold-start or semantic/source-revision path has one narrower requirement: after ASCII generation and before layout, use a fresh-context independent topology Reviewer when delegation is available. This is a semantic acceptance checkpoint, not continuous parallel drawing. It is not rerun for visual-only iterations while the digest-bound review remains current. If delegation is unavailable, semantic acceptance remains pending and strict delivery cannot claim PASS; a same-agent reread is useful but not independent.

- Keep one topology owner responsible for the hierarchy tree, contracts, shared symbol dictionary, and conflict resolution.
- Keep one master composer responsible for final geometry, hierarchy arrows, Legend consistency, and integration. These roles may be the same agent and usually should be for medium-sized diagrams.
- Parallel agents may extract source/config evidence, derive tensor shapes, audit a contract, or independently review full-canvas and crop readability.
- The independent topology Reviewer first inventories pinned sources without Builder conclusions, does not edit semantic inputs, and writes only `topology-review.json`. Do not let the Builder and Reviewer concurrently modify the same artifacts.
- A focused module may be delegated only after its parent boundary, inputs, outputs, symbols, and expansion target are fixed. The agent should return evidence and a contract-compatible component, not invent a competing master layout.
- Resolve discrepancies in the topology contract before changing geometry. Do not average or visually merge conflicting interpretations.
- A final integration review must check cross-module symbol definitions, duplicated modules, branch corridors, semantic colors, and master/focused drift.

Avoid a one-shot “each agent draws a region, then stitch everything” workflow. Independent coordinate systems and implicit assumptions commonly produce inconsistent granularity, duplicated parents, and page-like seams in the final architecture.

## Geometry

- Canvas: white or near-white, with generous whitespace between subgraphs.
- Ordinary operator node: compact rectangular box with a deliberate but very small corner radius, roughly 3–5 px at native scale. It should still read as a rectangle, never as a pill, tile, or presentation card. In draw.io, use `rounded=1` with a very small `arcSize` (about 4–6), not the default large arc.
- Arithmetic operation: circle containing `+`, `×`, or another operator.
- Subgraph: tight black/gray dashed rectangle with square corners; its title sits in the upper-right or upper-left inside edge.
- Tensor-flow edge: black, thin, orthogonal, solid arrowhead. Avoid decorative colors.
- Hierarchy expansion: in a hierarchy master, use a large white hollow block arrow or wide white hollow orthogonal arrow with gray/black outline between the exact parent and expanded child. Bends are allowed and preferred when they make the source and target precise. Do not attach tensor-shape labels to it. Do not use this symbol as a substitute for tensor dependencies in an end-to-end view.
- Typography: compact sans-serif with role-based sizes derived from the declared viewing profile. Native size is not an acceptance metric by itself; follow “Presentation scale, typography, and collision budget.”

## Semantic Legend

Use the fixed DPSK V4 palette below. The executable rules, inference boundaries,
TP overlay, and mandatory Legend gate are defined in
[semantic-color-legend-contract.md](semantic-color-legend-contract.md).

| Class | Fill | Border | Notes |
|---|---|---|---|
| 条件执行 | `#FFFFFF` | `#111111` dashed | Genuine runtime condition only |
| Tensor Op | `#DAE8FC` | `#6C8EBF` | Linear, GEMM, einsum, projection |
| Vector Op | `#FFE6CC` | `#D79B00` | RMSNorm, sigmoid, SiLU, softmax |
| IO Op | `#FFF2CC` | `#D6B656` | reshape, split, cat, gather, cast |
| TP 拆分 | preserve base class | preserve base class | Overlay: red text for TP-specific nodes; white swatch only in the Legend |
| 通信 | `#D5E8D4` | `#82B366` | all_reduce, all_gather, reduce_scatter |
| 组合操作 | `#F8CECC` | `#B85450` | attention, compressor, fused rule |
| 残差操作 | `#F5F5F5` | `#666666` | residual/hyper-connection boundary |
| Cache | `#B0E3E6` | `#0E8992` | KV, convolution, recurrent state |

Do not assign a unique color to an attention family, state-space mixer, expert layer, auxiliary head, or other named module merely to distinguish identity. Its internal nodes must use the semantic classes above.
Do not hand-style these colors in XML. Set or infer the IR semantic class and let
the compiler emit both node styles and the one complete master Legend.

## Hierarchy and topology

- First establish the main repeated architecture, analogous to the encoder/decoder stack in *Attention Is All You Need*.
- Show one representative repeated block, then annotate its repetition count.
- Expand a representative layer separately. Expand its major submodules separately again only when needed.
- For a static hybrid cadence such as `12 × [Local, Local, Local, Global]`, draw the fixed four-layer cadence, or `Local ×3 → Global ×1`; never draw it as a runtime `if` decision.
- If prefill and decode execute different graphs, map each path to its own named `operator_sequence` and `runtime_variant_contract`, then optionally group it with a dashed visual boundary. Show shared state/cache explicitly. Persistent storage uses the slanted cache/state glyph in a side lane; cache read/write/update operations remain ordinary operator rectangles and the storage node never belongs to the main operator sequence.

## Shape annotation

- Put the tensor shape beside the edge segment that carries it, for example `(b,s,h,D)` or `[B,S,4,D]`.
- Label shapes immediately before and after split, reshape, unflatten, head replication, cache update, and collective communication.
- Define symbols once near the Legend. Do not repeat long explanatory prose in operator boxes.

## Visual acceptance test

At the declared full-canvas target viewport, the viewer must be able to identify:

1. the main topology;
2. every expansion relationship;
3. the title and ownership of every dashed block;
4. distinct branches without zooming.

At the declared detail scale, the viewer must be able to trace a tensor from input to output and read every shape transition without consulting prose outside the graph. Export and inspect the actual target-size raster, not only a zoomable editor view; also inspect at least two native-detail crops for clipping, fallback-font reflow, and label/edge collisions.

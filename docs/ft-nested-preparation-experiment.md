# Direct nested preparation on free-threaded Darwin

This candidate changes only schema-validated output preparation on the existing FT Darwin graph path. It does not change HTTP parsing, connection ownership, worker-wide scheduling, native JSON encoding, or the response envelope. Only the private direct capture bypasses the per-preparation policy scope; its incumbent fallback retains that scope.

## Selection and supported shapes

Registration captures the existing inspection metadata and compiles a narrow required-field Struct graph into direct projection code. Eligible roots are nested required Structs or lists of eligible Structs; nested fields may be eligible Structs, lists of them, or unconstrained primitive scalars. Flat root contracts retain their incumbent strategy.

Defaults, constrained fields or lists, recursive contracts, tags, array-like or dictionary-enabled Structs, and custom class/field access are excluded. Unsupported schemas retain the graph. Unsupported runtime values, subclasses, nonfinite values and missing fields return the original root to the actual selected incumbent, preserving its projection and rejection behavior rather than using a universal native-codec oracle.

GIL-enabled execution retains its canonical preparer. Linux retains its existing owned graph. Selection happens at registration; requests do not query GIL state.

## Ownership and mutation

A worker receives private generated functions and globals, class-guard containers and mappingproxy views, missing sentinel, and bound slot getters. Code objects and schema classes may remain shared. Worker binding consumes registration metadata rather than re-inspecting mutable annotations or executing registration effects again.

Class guards detect completed access/descriptor changes and fall back before capture. Captured slot getters prevent a descriptor replaced between the guard and read from introducing a callback into the direct path. This is not an atomic transaction over concurrent schema or instance mutations; field values are captured and checked individually into owned public containers.

The existing graph remains worker-owned as the fallback. Direct captures execute without per-request Mach policy RPCs. The incumbent fallback alone retains its previous policy scope and restoration on success or failure, including restoration-failure reporting. Contracts that are not eligible for direct capture retain their original outer scope. No worker-wide policy or system setting changes. The encoder, checked-response Request protection, framing and status/header handling remain unchanged.

## Qualification boundary

Focused tests cover activation through EndpointPlan, private worker execution/guards, original-root fallback, missing slots, descriptor replacement during capture, numeric normalization/nonfinite rejection, constrained/recursive exclusions, discarded private subtype fields and frozen metadata.

Earlier fixture-side HTTP results motivated integration but do not measure this final module: captured slot getters and production selection require a fresh installed-artifact campaign. A passing component screen does not establish fixed-load SLOs, mixed-traffic or cross-platform qualification. All earlier adverse records and unchanged gates remain relevant. This document makes no shipped speed claim.

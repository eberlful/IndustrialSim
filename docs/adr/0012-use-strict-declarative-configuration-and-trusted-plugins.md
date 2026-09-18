# Use strict declarative configuration and trusted plugins

Human-authored models use YAML 1.2 validated strictly against versioned Pydantic schemas, with unknown fields treated as errors. New behavior is supplied only by explicitly approved local plugins registered through stable type IDs and Python entry points; duplicate IDs, missing versions, dynamic code in configuration, and implicit import paths are rejected to keep model loading predictable and auditable.

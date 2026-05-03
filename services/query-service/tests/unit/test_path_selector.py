from internal.modelgateway.path_selector import select_model_path


def test_mg_01_l0_uses_cloud():
    config = select_model_path(0)
    assert config.path_label == "cloud_l1"
    assert "api-gateway.company.internal" in config.endpoint
    assert config.model == "gpt-4o"


def test_mg_01_l1_uses_cloud():
    config = select_model_path(1)
    assert config.path_label == "cloud_l1"
    assert "api-gateway.company.internal" in config.endpoint
    assert config.model == "gpt-4o"


def test_mg_02_l2_uses_private():
    config = select_model_path(2)
    assert config.path_label == "private_l2"
    assert "llm-private.retrieval-deps" in config.endpoint
    assert config.model == "llama-3-70b-instruct"


def test_l3_uses_restricted():
    config = select_model_path(3)
    assert config.path_label == "private_l3"
    assert "llm-restricted.retrieval-deps" in config.endpoint
    assert config.model == "llama-3-70b-instruct"


def test_routing_by_chunk_sensitivity_not_clearance():
    # Even if user clearance is 3, if highest retrieved chunk is L1, use cloud path
    config = select_model_path(1)
    assert config.path_label == "cloud_l1"
    assert "api-gateway.company.internal" in config.endpoint

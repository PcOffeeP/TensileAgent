"""TensileAgent test-suite boundaries.

Training-pipeline modules were moved to the sibling mVllm_2 repository. The
historical test files remain temporarily for traceability, but collecting them
here would test modules this repository intentionally no longer ships.
"""

collect_ignore = [
    "test_calibration.py",
    "test_configure_processor_max_frames.py",
    "test_dataset_manager.py",
    "test_freeze_data_version.py",
    "test_preprocessing_adapter.py",
    "test_quality_check.py",
    "test_run_inference.py",
    "test_server_adapter.py",
    "test_server_proxy.py",
    "test_subvideo_builder.py",
    "test_training_sample_builder.py",
    "test_validate_no_oob.py",
    "test_validation_common.py",
]


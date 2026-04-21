class RecoveryError(Exception):
    pass


def recover_baseline(*args, **kwargs):
    raise RecoveryError(
        "Recovery requires explicit Beo-approved artifact and separate EAG-1 approval. Not yet implemented."
    )

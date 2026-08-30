import time


def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "worker",
        "execution": "deferred-to-phase-3",
        "external_integrations": "disabled",
    }


def main() -> None:
    print(health(), flush=True)
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("worker shutdown requested", flush=True)


if __name__ == "__main__":
    main()

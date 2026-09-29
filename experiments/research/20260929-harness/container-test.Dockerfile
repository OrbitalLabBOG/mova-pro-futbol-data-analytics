# Test tooling only; the application image and production configuration stay intact.
FROM mova-fpl-engine:harness-integrity-fc07672
USER root
RUN python -m pip install --no-cache-dir pytest==8.4.2 && python -m pip check
RUN apt-get update && apt-get install -y --no-install-recommends nodejs git && rm -rf /var/lib/apt/lists/*
USER 10001:10001
ENV HOME=/tmp PYTHONPATH=/app:/proof
WORKDIR /proof
ENTRYPOINT ["python", "-m", "pytest"]
CMD ["-q", "-p", "no:cacheprovider", "--override-ini=pythonpath=/app /proof"]

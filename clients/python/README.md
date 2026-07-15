# headway-client

The analyst's door into a [Headway](https://github.com/headway-transit/headway)
deployment: typed, provenance-preserving Python access to computed transit
metrics, the lineage graph, and the data-quality workflow.

> Explore and compute freely: nothing computed outside Headway's calculation
> library (services/calc) can ever become a reported figure. Only the
> calculation library writes computed.metric_values, and the walls are
> structural database CHECKs, not policy.

That is the whole trust model. This client is a read-only consumer — you can
slice, model, and chart anything, and none of it can flow back into what the
agency reports.

## Install

Not yet on PyPI (deliberately — publication is a Community Maintainer
decision once the library stabilizes). Install from the repository:

```sh
pip install ./clients/python              # core: httpx only
pip install './clients/python[pandas]'    # + DataFrame helpers
```

## Use

```python
from headway_client import HeadwayClient, frames

hw = HeadwayClient("http://127.0.0.1:8000", token="hwk_…your machine key…")

values = hw.metric_values(metric="vrm")          # typed MetricValue rows
df = frames.metric_values_frame(values)          # provenance columns ALWAYS present

trail = hw.walk_lineage(values[0].metric_value_id)  # figure → raw records
trail.raw_record_ids()                              # the content-addressed bottom

public = HeadwayClient("http://127.0.0.1:8000").public_certified()  # no credential
```

Every figure crosses the wire as an exact decimal string and lands in
DataFrames as `decimal.Decimal` — floating point never touches a reported
value. Every metric-value frame always carries `metric_value_id`,
`calc_name`, `calc_version`, `category`, `certification_status`,
`simulated`, and `source_mix`; there is no option to omit them. Dropping
provenance is your explicit act, never this library's default.

## Credentials, honestly

| Surface | Credential |
| --- | --- |
| `metric_values` / `machine_metrics` | machine API key (`hwk_…`, scope `read:metrics`) or session token |
| `lineage` / `walk_lineage` | machine API key or session token |
| `public_certified` | none |
| `compare`, `dq_issues`, `dq_issue_counts` | session token only (`headway_client.login`) — the API does not yet take machine keys here, and this client relays that 401 rather than papering over it |

How to get a machine key (an administrator issues it) and how the read-only
SQL role compares: [docs/analyst-access.md](../../docs/analyst-access.md).
Worked examples: [notebooks/](../../notebooks/).

## Tests

```sh
pip install -e './clients/python[pandas,test]'
cd clients/python && python -m pytest -q
```

Unit tests run against a contract-shaped fake transport (httpx.MockTransport)
— no live deployment needed. Live-stack verification evidence lives in
handoff 0018.

## License

Apache-2.0, like the rest of Headway.

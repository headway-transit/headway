import { LineageGraph } from 'web';

/**
 * The provenance trail LineageView draws: one certified VRM figure produced
 * by vrm_v0 0.2.0 from three raw AVL record batches (64-hex source ids).
 * The raw tier starts collapsed as its count node, exactly as served.
 */
export const CertifiedVrmTrail = () => (
  <LineageGraph
    root={{
      kind: 'computed.metric_values',
      id: 'b3ebdef6-9d1c-4f4a-8a3e-6c2d0e5b7a91',
      transform_name: 'vrm_v0',
      transform_version: '0.2.0',
      inputs: [
        {
          kind: 'raw.records',
          id: '4f8a2c9e71b35d06e2a4c8f01b6d3957a0e5c2d84b7f1a6390c5e8d2417b6f03',
          transform_name: null,
          transform_version: null,
          inputs: [],
        },
        {
          kind: 'raw.records',
          id: '9c1e5b7d30a2f486c9d1e3b5a7f02468bd13579ce02468ace13579bdf0246810',
          transform_name: null,
          transform_version: null,
          inputs: [],
        },
        {
          kind: 'raw.records',
          id: '61d4a8f2c50b9e37d16a4c8e2f50b9d371c6a0e4f82b5d19c73e60a4d28f5b91',
          transform_name: null,
          transform_version: null,
          inputs: [],
        },
      ],
    }}
  />
);

import { Modal } from 'web';

/**
 * The certify-attestation dialog as CertifyView composes it: heading names
 * the dialog (titleId), the figure is restated verbatim, and the attestation
 * textarea + Certify/Cancel actions sit in .modal-actions.
 */
export const CertifyAttestation = () => (
  <Modal titleId="certify-modal-title" onClose={() => {}}>
    <h2 id="certify-modal-title">Certify these figures</h2>
    <p>
      Vehicle Revenue Miles (VRM), 2026-07-09 to 2026-07-11:{' '}
      <strong>12794.92 miles</strong> — calculated by vrm_v0 0.2.0.
    </p>
    <form onSubmit={(e) => e.preventDefault()}>
      <label htmlFor="certify-attestation">Attestation statement</label>
      <textarea
        id="certify-attestation"
        placeholder="I have reviewed the July service-mileage figure against the AVL exports and believe it to be correct."
      />
      <div className="modal-actions">
        <button type="submit" className="primary">
          Certify
        </button>
        <button type="button">Cancel</button>
      </div>
    </form>
  </Modal>
);

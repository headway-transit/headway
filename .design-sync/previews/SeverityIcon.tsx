import { SeverityIcon } from 'web';

/** The app pairs the icon with its severity chip (icon + label + color — never color alone). */
const Chip = ({ s, label }: { s: string; label: string }) => (
  <span className={`chip severity ${s}`} style={{ marginRight: '0.75rem' }}>
    <SeverityIcon severity={s} /> {label}
  </span>
);

/** The three data-quality severities as chips, the way the DQ queue renders them. */
export const AllSeverities = () => (
  <div>
    <Chip s="blocking" label="Blocking" />
    <Chip s="warning" label="Warning" />
    <Chip s="info" label="Info" />
  </div>
);

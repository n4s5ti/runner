import SettingsField from '../SettingsField.js';

const Personalization = ({ fields, values }) => {
  return (
    <div className="flex-1 space-y-6 overflow-y-auto px-6 py-6">
      {fields.map((field) => (
        <SettingsField
          key={field.key}
          field={field}
          value={
            (field.scope === 'client'
              ? localStorage.getItem(field.key)
              : values[field.key]) ?? field.default
          }
          dataAdd="personalization"
        />
      ))}
    </div>
  );
};

export default Personalization;

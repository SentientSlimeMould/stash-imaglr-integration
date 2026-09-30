// SPDX-License-Identifier: AGPL-3.0-only
// A confirmation like Stash's own (ModalComponent, as its delete dialogs use it): a small modal with a
// title, the question, Cancel and one accept button. Replaces the browser's confirm() popup.
import React from "react";

interface Props {
  title: string;
  accept: string;
  variant?: string; // accept button; "danger" for anything that removes something
  busy?: boolean; // both buttons off while the action runs
  disabled?: boolean; // accept off (nothing valid to accept yet)
  onAccept: () => void;
  onCancel: () => void;
  children: React.ReactNode;
}

export function ConfirmDialog({ title, accept, variant = "primary", busy, disabled, onAccept, onCancel, children }: Props) {
  const { Modal, Button } = PluginApi.libraries.Bootstrap;
  return (
    <Modal show onHide={() => undefined} keyboard={false}>
      <Modal.Header>
        <Modal.Title>{title}</Modal.Title>
      </Modal.Header>
      <Modal.Body>{children}</Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>Cancel</Button>
        <Button variant={variant} onClick={onAccept} disabled={busy || disabled}>{accept}</Button>
      </Modal.Footer>
    </Modal>
  );
}

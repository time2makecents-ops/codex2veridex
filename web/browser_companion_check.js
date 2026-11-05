document.getElementById('show-result').addEventListener('click', () => {
  document.getElementById('test-result').textContent =
    `Companion test passed: ${document.getElementById('test-note').value || 'no note'}`;
});

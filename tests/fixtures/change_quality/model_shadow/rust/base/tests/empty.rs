use loopx_quality_shadow_rust::first_or_default;

#[test]
fn empty_slice_uses_default() {
    assert_eq!(first_or_default(&[]), 0);
}

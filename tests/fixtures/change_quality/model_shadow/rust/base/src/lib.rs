pub fn first_or_default(values: &[i32]) -> i32 {
    values.first().copied().unwrap_or_default()
}

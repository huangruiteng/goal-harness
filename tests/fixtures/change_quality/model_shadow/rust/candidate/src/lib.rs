fn first(values: &[i32]) -> Option<&i32> {
    values.first()
}

fn copied_or_default(value: Option<&i32>) -> i32 {
    value.copied().unwrap_or_default()
}

pub fn first_or_default(values: &[i32]) -> i32 {
    copied_or_default(first(values))
}

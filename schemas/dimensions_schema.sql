create table dimensions (
    id text primary key,
    dimension_type text not null,
    aggregation_method text not null,
    display_order integer not null,
    active boolean default true,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table dimension_columns (
    id bigint generated always as identity primary key,
    dimension_id text not null references dimensions(id) on delete cascade,
    source_column text not null,
    sort_order integer not null default 1
);

create table dimension_values (
    id bigint generated always as identity primary key,
    dimension_id text not null references dimensions(id) on delete cascade,
    value text not null
);

create table dimension_operations (
    dimension_id text primary key references dimensions(id) on delete cascade,
    operation text not null
);

create table dimension_bins (
    id bigint generated always as identity primary key,
    dimension_id text not null references dimensions(id) on delete cascade,
    min_value numeric not null,
    max_value numeric not null,
    label text not null
);

create index idx_dimension_columns_dimension_id on dimension_columns(dimension_id);
create index idx_dimension_values_dimension_id on dimension_values(dimension_id);
create index idx_dimension_bins_dimension_id on dimension_bins(dimension_id);
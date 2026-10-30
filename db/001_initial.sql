BEGIN;

-- Adds GiST equality operators for bigint, used by the room overlap constraint.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE users (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL CHECK (btrim(name) <> ''),
    email text NOT NULL CHECK (btrim(email) <> '' AND email = btrim(email)),
    password_hash text NOT NULL CHECK (btrim(password_hash) <> ''),
    role text NOT NULL DEFAULT 'participant'
        CHECK (role IN ('participant', 'organizer')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_unique ON users (lower(email));

CREATE TABLE events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organizer_id bigint NOT NULL REFERENCES users(id),
    title text NOT NULL CHECK (btrim(title) <> ''),
    description text NOT NULL DEFAULT '',
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    timezone text NOT NULL DEFAULT 'Europe/Moscow',
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (starts_at < ends_at)
);
CREATE INDEX events_organizer_idx ON events (organizer_id);

CREATE TABLE rooms (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    capacity integer NOT NULL CHECK (capacity > 0),
    UNIQUE (event_id, name),
    UNIQUE (id, event_id)
);

CREATE TABLE activities (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    room_id bigint NOT NULL,
    title text NOT NULL CHECK (btrim(title) <> ''),
    description text NOT NULL DEFAULT '',
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    capacity integer NOT NULL CHECK (capacity > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (starts_at < ends_at),
    -- A room must belong to the same event as its activity.
    FOREIGN KEY (room_id, event_id) REFERENCES rooms(id, event_id),
    -- Half-open intervals: 10:00-11:00 and 11:00-12:00 are compatible.
    CONSTRAINT activities_room_no_overlap EXCLUDE USING gist (
        room_id WITH =,
        tstzrange(starts_at, ends_at, '[)') WITH &&
    )
);
CREATE INDEX activities_event_start_idx ON activities (event_id, starts_at, id);

-- Cancellation deletes the row. Audit/history can be added separately later.
CREATE TABLE registrations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES users(id),
    activity_id bigint NOT NULL REFERENCES activities(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, activity_id)
);
-- UNIQUE above covers personal schedules; this index covers occupancy queries.
CREATE INDEX registrations_activity_idx ON registrations (activity_id);

COMMIT;

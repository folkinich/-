\set ON_ERROR_STOP on
BEGIN;

DO $$
DECLARE
    participant bigint;
    organizer bigint;
    event_one bigint;
    event_two bigint;
    room_one bigint;
    activity_one bigint;
BEGIN
    INSERT INTO users(name, email, password_hash)
        VALUES ('Participant', 'db-test-participant@example.test', 'test-only-not-a-real-hash')
        RETURNING id INTO participant;
    INSERT INTO users(name, email, password_hash, role)
        VALUES ('Organizer', 'db-test-organizer@example.test', 'test-only-not-a-real-hash', 'organizer')
        RETURNING id INTO organizer;
    INSERT INTO events(organizer_id, title, starts_at, ends_at)
        VALUES (organizer, 'One', '2027-01-01 09:00+03', '2027-01-01 18:00+03')
        RETURNING id INTO event_one;
    INSERT INTO events(organizer_id, title, starts_at, ends_at)
        VALUES (organizer, 'Two', '2027-01-01 09:00+03', '2027-01-01 18:00+03')
        RETURNING id INTO event_two;
    INSERT INTO rooms(event_id, name, capacity) VALUES (event_one, 'A', 2)
        RETURNING id INTO room_one;
    INSERT INTO activities(event_id, room_id, title, starts_at, ends_at, capacity)
        VALUES (event_one, room_one, 'First', '2027-01-01 10:00+03', '2027-01-01 11:00+03', 2)
        RETURNING id INTO activity_one;
    INSERT INTO activities(event_id, room_id, title, starts_at, ends_at, capacity)
        VALUES (event_one, room_one, 'Adjacent', '2027-01-01 11:00+03', '2027-01-01 12:00+03', 2);
    BEGIN
        INSERT INTO activities(event_id, room_id, title, starts_at, ends_at, capacity)
            VALUES (event_one, room_one, 'Overlap', '2027-01-01 10:30+03', '2027-01-01 11:30+03', 2);
        RAISE EXCEPTION 'Expected room overlap rejection';
    EXCEPTION WHEN exclusion_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO activities(event_id, room_id, title, starts_at, ends_at, capacity)
            VALUES (event_two, room_one, 'Wrong event', '2027-01-01 13:00+03', '2027-01-01 14:00+03', 2);
        RAISE EXCEPTION 'Expected event/room mismatch rejection';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO rooms(event_id, name, capacity) VALUES (event_one, 'Invalid', 0);
        RAISE EXCEPTION 'Expected zero capacity rejection';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO activities(event_id, room_id, title, starts_at, ends_at, capacity)
            VALUES (event_one, room_one, 'Invalid time', '2027-01-01 14:00+03', '2027-01-01 14:00+03', 2);
        RAISE EXCEPTION 'Expected empty interval rejection';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO users(name, email, password_hash)
            VALUES ('Duplicate email', 'DB-TEST-PARTICIPANT@example.test', 'test-only');
        RAISE EXCEPTION 'Expected case-insensitive email uniqueness';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    INSERT INTO registrations(user_id, activity_id) VALUES (participant, activity_one);
    BEGIN
        INSERT INTO registrations(user_id, activity_id) VALUES (participant, activity_one);
        RAISE EXCEPTION 'Expected duplicate registration rejection';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    DELETE FROM registrations WHERE user_id = participant AND activity_id = activity_one;
    INSERT INTO registrations(user_id, activity_id) VALUES (participant, activity_one);
    RAISE NOTICE 'PASS: adjacent slots, overlap, room/event ownership, capacity, time, email, duplicate registration, cancellation/re-registration';
END $$;

ROLLBACK;

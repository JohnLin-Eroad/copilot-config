# TripSummary Implementation - Java 21 Spring Boot 3.4

## Domain Layer - Pure Domain Model

### File: `api/domain/src/main/java/com/eroad/trip/domain/model/TripSummary.java`

```java
package com.eroad.trip.domain.model;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

/**
 * Immutable domain model representing a completed trip summary.
 * This read model aggregates trip events and computed metrics for analysis.
 *
 * @param tripId          Unique identifier for the trip
 * @param vehicleId       Unique identifier for the vehicle
 * @param driverId        Unique identifier for the driver
 * @param startTime       Trip start timestamp
 * @param endTime         Trip end timestamp
 * @param distanceKm      Total distance traveled in kilometers
 * @param durationMinutes Duration of trip in minutes
 * @param averageSpeedKmh Average speed during trip in km/h
 * @param fuelUsedLitres  Optional fuel consumption in litres
 */
public record TripSummary(
    UUID tripId,
    UUID vehicleId,
    UUID driverId,
    Instant startTime,
    Instant endTime,
    double distanceKm,
    long durationMinutes,
    double averageSpeedKmh,
    Optional<Double> fuelUsedLitres
) {
    
    /**
     * Computes fuel efficiency in litres per 100km.
     *
     * @return Optional containing fuel efficiency, empty if no fuel data available
     */
    public Optional<Double> fuelEfficiency() {
        return fuelUsedLitres.map(litres -> {
            if (distanceKm <= 0) {
                return 0.0;
            }
            return (litres / distanceKm) * 100;
        });
    }
    
    /**
     * Computes the duration of the trip as a Java Duration object.
     *
     * @return Duration between start and end times
     */
    public Duration duration() {
        return Duration.between(startTime, endTime);
    }
    
    /**
     * Determines if the trip qualifies as long-haul.
     * Long-haul trips are those exceeding 200km or 4 hours duration.
     *
     * @return true if trip distance > 200km or duration > 4 hours, false otherwise
     */
    public boolean isLongHaul() {
        return distanceKm > 200 || durationMinutes > 240;
    }
    
    /**
     * Projects a TripSummary from domain events.
     * Combines trip start/completion events with optional fuel record.
     *
     * @param start    the trip started event
     * @param end      the trip completed event
     * @param fuel     optional fuel record for the trip
     * @return new TripSummary instance
     */
    public static TripSummary from(
        TripStartedEvent start,
        TripCompletedEvent end,
        Optional<FuelRecord> fuel
    ) {
        Duration tripDuration = Duration.between(start.startTime(), end.endTime());
        long durationMinutes = tripDuration.toMinutes();
        double averageSpeed = durationMinutes > 0
            ? (end.distanceKm() / (durationMinutes / 60.0))
            : 0.0;
        
        Optional<Double> fuelUsed = fuel.map(FuelRecord::litresUsed);
        
        return new TripSummary(
            start.tripId(),
            start.vehicleId(),
            start.driverId(),
            start.startTime(),
            end.endTime(),
            end.distanceKm(),
            durationMinutes,
            averageSpeed,
            fuelUsed
        );
    }
}
```

### File: `api/domain/src/main/java/com/eroad/trip/domain/event/TripStartedEvent.java`

```java
package com.eroad.trip.domain.event;

import java.time.Instant;
import java.util.UUID;

/**
 * Domain event published when a trip begins.
 *
 * @param tripId      Unique identifier for the trip
 * @param vehicleId   Unique identifier for the vehicle
 * @param driverId    Unique identifier for the driver
 * @param startTime   Timestamp when the trip started
 */
public record TripStartedEvent(
    UUID tripId,
    UUID vehicleId,
    UUID driverId,
    Instant startTime
) {
}
```

### File: `api/domain/src/main/java/com/eroad/trip/domain/event/TripCompletedEvent.java`

```java
package com.eroad.trip.domain.event;

import java.time.Instant;
import java.util.UUID;

/**
 * Domain event published when a trip ends.
 *
 * @param tripId       Unique identifier for the trip
 * @param endTime      Timestamp when the trip completed
 * @param distanceKm   Total distance traveled during the trip in kilometers
 */
public record TripCompletedEvent(
    UUID tripId,
    Instant endTime,
    double distanceKm
) {
}
```

### File: `api/domain/src/main/java/com/eroad/trip/domain/model/FuelRecord.java`

```java
package com.eroad.trip.domain.model;

import java.util.UUID;

/**
 * Domain model representing fuel consumption for a trip.
 *
 * @param tripId        Unique identifier for the trip
 * @param litresUsed    Amount of fuel consumed during the trip in litres
 */
public record FuelRecord(
    UUID tripId,
    double litresUsed
) {
}
```

## Application/Infrastructure Layer - DTO and Mapper

### File: `api/application/src/main/java/com/eroad/trip/application/dto/TripSummaryDto.java`

```java
package com.eroad.trip.application.dto;

import java.util.Optional;

/**
 * Data transfer object for trip summary API responses.
 * All timestamps are represented in ISO 8601 format as strings.
 *
 * @param tripId            Trip identifier as string
 * @param vehicleId         Vehicle identifier as string
 * @param driverId          Driver identifier as string
 * @param startTime         Trip start time in ISO 8601 format
 * @param endTime           Trip end time in ISO 8601 format
 * @param distanceKm        Distance traveled in kilometers
 * @param durationMinutes   Trip duration in minutes
 * @param averageSpeedKmh   Average speed during trip in km/h
 * @param fuelUsedLitres    Optional fuel consumption in litres
 * @param fuelEfficiency    Optional fuel efficiency in litres per 100km
 * @param isLongHaul        Whether this trip qualifies as long-haul
 */
public record TripSummaryDto(
    String tripId,
    String vehicleId,
    String driverId,
    String startTime,
    String endTime,
    double distanceKm,
    long durationMinutes,
    double averageSpeedKmh,
    Double fuelUsedLitres,
    Double fuelEfficiency,
    boolean isLongHaul
) {
}
```

### File: `api/application/src/main/java/com/eroad/trip/application/mapper/TripSummaryMapper.java`

```java
package com.eroad.trip.application.mapper;

import com.eroad.trip.domain.model.TripSummary;
import com.eroad.trip.application.dto.TripSummaryDto;

/**
 * Mapper for converting TripSummary domain model to TripSummaryDto API response object.
 * Handles transformation of timestamps to ISO 8601 format and optional computed fields.
 */
public class TripSummaryMapper {
    
    /**
     * Converts a TripSummary domain model to a TripSummaryDto suitable for API responses.
     *
     * @param tripSummary the domain model to convert
     * @return TripSummaryDto with all fields in API-friendly format
     */
    public static TripSummaryDto toDto(TripSummary tripSummary) {
        return new TripSummaryDto(
            tripSummary.tripId().toString(),
            tripSummary.vehicleId().toString(),
            tripSummary.driverId().toString(),
            tripSummary.startTime().toString(),
            tripSummary.endTime().toString(),
            tripSummary.distanceKm(),
            tripSummary.durationMinutes(),
            tripSummary.averageSpeedKmh(),
            tripSummary.fuelUsedLitres().orElse(null),
            tripSummary.fuelEfficiency().orElse(null),
            tripSummary.isLongHaul()
        );
    }
}
```

## Test Layer - Comprehensive JUnit 5 Tests

### File: `api/application/src/test/java/com/eroad/trip/domain/model/TripSummaryTest.java`

```java
package com.eroad.trip.domain.model;

import com.eroad.trip.domain.event.TripCompletedEvent;
import com.eroad.trip.domain.event.TripStartedEvent;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Comprehensive test suite for TripSummary domain model.
 * Tests factory projection, computed methods, and edge cases.
 */
class TripSummaryTest {
    
    private static final UUID TRIP_ID = UUID.randomUUID();
    private static final UUID VEHICLE_ID = UUID.randomUUID();
    private static final UUID DRIVER_ID = UUID.randomUUID();
    private static final Instant START_TIME = Instant.parse("2026-06-24T08:00:00Z");
    private static final Instant END_TIME = Instant.parse("2026-06-24T12:00:00Z");
    
    @Test
    void testFactoryProjectionFromEvents() {
        // Arrange
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, END_TIME, 400.0);
        FuelRecord fuelRecord = new FuelRecord(TRIP_ID, 32.0);
        
        // Act
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.of(fuelRecord));
        
        // Assert
        assertEquals(TRIP_ID, summary.tripId());
        assertEquals(VEHICLE_ID, summary.vehicleId());
        assertEquals(DRIVER_ID, summary.driverId());
        assertEquals(START_TIME, summary.startTime());
        assertEquals(END_TIME, summary.endTime());
        assertEquals(400.0, summary.distanceKm());
        assertEquals(240, summary.durationMinutes());
        assertEquals(100.0, summary.averageSpeedKmh(), 0.01);
        assertTrue(summary.fuelUsedLitres().isPresent());
        assertEquals(32.0, summary.fuelUsedLitres().get());
    }
    
    @Test
    void testFactoryProjectionWithoutFuel() {
        // Arrange
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, END_TIME, 200.0);
        
        // Act
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Assert
        assertTrue(summary.fuelUsedLitres().isEmpty());
        assertTrue(summary.fuelEfficiency().isEmpty());
    }
    
    @Test
    void testComputedDuration() {
        // Arrange
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, END_TIME, 100.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act
        Duration duration = summary.duration();
        
        // Assert
        assertEquals(4, duration.toHours());
        assertEquals(240, duration.toMinutes());
    }
    
    @Test
    void testFuelEfficiencyComputation() {
        // Arrange
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, END_TIME, 400.0);
        FuelRecord fuelRecord = new FuelRecord(TRIP_ID, 32.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.of(fuelRecord));
        
        // Act
        Optional<Double> efficiency = summary.fuelEfficiency();
        
        // Assert
        assertTrue(efficiency.isPresent());
        assertEquals(8.0, efficiency.get(), 0.01); // 32L / 400km * 100
    }
    
    @Test
    void testFuelEfficiencyWithZeroDistance() {
        // Arrange
        Instant start = Instant.parse("2026-06-24T08:00:00Z");
        Instant end = Instant.parse("2026-06-24T08:30:00Z");
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, start);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, end, 0.0);
        FuelRecord fuelRecord = new FuelRecord(TRIP_ID, 5.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.of(fuelRecord));
        
        // Act
        Optional<Double> efficiency = summary.fuelEfficiency();
        
        // Assert
        assertTrue(efficiency.isPresent());
        assertEquals(0.0, efficiency.get());
    }
    
    @Test
    void testIsLongHaulByDistance() {
        // Arrange - distance > 200km, duration < 4 hours
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        Instant shortEnd = Instant.parse("2026-06-24T09:00:00Z");
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, shortEnd, 250.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act & Assert
        assertTrue(summary.isLongHaul());
    }
    
    @Test
    void testIsLongHaulByDuration() {
        // Arrange - duration > 4 hours, distance < 200km
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        Instant longEnd = Instant.parse("2026-06-24T13:00:00Z"); // 5 hours
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, longEnd, 150.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act & Assert
        assertTrue(summary.isLongHaul());
    }
    
    @Test
    void testIsNotLongHaulBelowThresholds() {
        // Arrange - distance < 200km, duration < 4 hours
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        Instant shortEnd = Instant.parse("2026-06-24T10:00:00Z");
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, shortEnd, 150.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act & Assert
        assertFalse(summary.isLongHaul());
    }
    
    @Test
    void testIsLongHaulExactly200KmBoundary() {
        // Arrange - exactly at boundary (200km)
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        Instant end = Instant.parse("2026-06-24T10:00:00Z");
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, end, 200.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act & Assert
        assertFalse(summary.isLongHaul()); // Not > 200, so false
    }
    
    @Test
    void testIsLongHaulExactly240MinutesBoundary() {
        // Arrange - exactly at duration boundary (240 minutes = 4 hours)
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, END_TIME, 100.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act & Assert
        assertFalse(summary.isLongHaul()); // Not > 240, so false
    }
    
    @Test
    void testAverageSpeedCalculation() {
        // Arrange - 300km in 3 hours = 100 km/h
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        Instant end = Instant.parse("2026-06-24T11:00:00Z");
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, end, 300.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act & Assert
        assertEquals(100.0, summary.averageSpeedKmh(), 0.01);
    }
    
    @Test
    void testAverageSpeedWithZeroDuration() {
        // Arrange - same start and end time
        Instant time = Instant.parse("2026-06-24T08:00:00Z");
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, time);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, time, 100.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act & Assert
        assertEquals(0.0, summary.averageSpeedKmh());
    }
    
    @Test
    void testImmutabilityOfRecord() {
        // Arrange
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, END_TIME, 100.0);
        TripSummary summary1 = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act - Try to create another with same values
        TripSummary summary2 = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Assert - Records with same values are equal
        assertEquals(summary1, summary2);
        assertEquals(summary1.hashCode(), summary2.hashCode());
    }
}
```

### File: `api/application/src/test/java/com/eroad/trip/application/mapper/TripSummaryMapperTest.java`

```java
package com.eroad.trip.application.mapper;

import com.eroad.trip.application.dto.TripSummaryDto;
import com.eroad.trip.domain.event.TripCompletedEvent;
import com.eroad.trip.domain.event.TripStartedEvent;
import com.eroad.trip.domain.model.FuelRecord;
import com.eroad.trip.domain.model.TripSummary;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Test suite for TripSummaryMapper.
 * Validates conversion from domain model to DTO.
 */
class TripSummaryMapperTest {
    
    private static final UUID TRIP_ID = UUID.randomUUID();
    private static final UUID VEHICLE_ID = UUID.randomUUID();
    private static final UUID DRIVER_ID = UUID.randomUUID();
    private static final Instant START_TIME = Instant.parse("2026-06-24T08:00:00Z");
    private static final Instant END_TIME = Instant.parse("2026-06-24T12:00:00Z");
    
    @Test
    void testMapToDtoWithAllFields() {
        // Arrange
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, END_TIME, 400.0);
        FuelRecord fuelRecord = new FuelRecord(TRIP_ID, 32.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.of(fuelRecord));
        
        // Act
        TripSummaryDto dto = TripSummaryMapper.toDto(summary);
        
        // Assert
        assertEquals(TRIP_ID.toString(), dto.tripId());
        assertEquals(VEHICLE_ID.toString(), dto.vehicleId());
        assertEquals(DRIVER_ID.toString(), dto.driverId());
        assertEquals("2026-06-24T08:00:00Z", dto.startTime());
        assertEquals("2026-06-24T12:00:00Z", dto.endTime());
        assertEquals(400.0, dto.distanceKm());
        assertEquals(240, dto.durationMinutes());
        assertEquals(100.0, dto.averageSpeedKmh(), 0.01);
        assertEquals(32.0, dto.fuelUsedLitres());
        assertEquals(8.0, dto.fuelEfficiency(), 0.01);
        assertTrue(dto.isLongHaul());
    }
    
    @Test
    void testMapToDtoWithoutFuelData() {
        // Arrange
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, END_TIME, 100.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act
        TripSummaryDto dto = TripSummaryMapper.toDto(summary);
        
        // Assert
        assertNull(dto.fuelUsedLitres());
        assertNull(dto.fuelEfficiency());
    }
    
    @Test
    void testMapToDtoTimestampFormat() {
        // Arrange
        Instant customStart = Instant.parse("2026-01-15T14:30:45Z");
        Instant customEnd = Instant.parse("2026-01-15T16:45:30Z");
        TripStartedEvent startEvent = new TripStartedEvent(TRIP_ID, VEHICLE_ID, DRIVER_ID, customStart);
        TripCompletedEvent endEvent = new TripCompletedEvent(TRIP_ID, customEnd, 150.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act
        TripSummaryDto dto = TripSummaryMapper.toDto(summary);
        
        // Assert
        assertEquals("2026-01-15T14:30:45Z", dto.startTime());
        assertEquals("2026-01-15T16:45:30Z", dto.endTime());
    }
    
    @Test
    void testMapToDtoUUIDsAsStrings() {
        // Arrange
        UUID customTripId = UUID.fromString("550e8400-e29b-41d4-a716-446655440000");
        UUID customVehicleId = UUID.fromString("6ba7b810-9dad-11d1-80b4-00c04fd430c8");
        UUID customDriverId = UUID.fromString("6ba7b811-9dad-11d1-80b4-00c04fd430c8");
        
        TripStartedEvent startEvent = new TripStartedEvent(customTripId, customVehicleId, customDriverId, START_TIME);
        TripCompletedEvent endEvent = new TripCompletedEvent(customTripId, END_TIME, 100.0);
        TripSummary summary = TripSummary.from(startEvent, endEvent, Optional.empty());
        
        // Act
        TripSummaryDto dto = TripSummaryMapper.toDto(summary);
        
        // Assert
        assertEquals("550e8400-e29b-41d4-a716-446655440000", dto.tripId());
        assertEquals("6ba7b810-9dad-11d1-80b4-00c04fd430c8", dto.vehicleId());
        assertEquals("6ba7b811-9dad-11d1-80b4-00c04fd430c8", dto.driverId());
    }
}
```

## Summary

This implementation follows **hexagonal architecture** principles:

- **Domain Layer** (`api/domain/`): Pure domain models as Java 21 records with no framework dependencies. Includes `TripSummary`, event records, and fuel record.
- **Application Layer** (`api/application/`): Mapper class and DTO record for API responses. Mapper handles transformation from domain to API-friendly format.
- **Tests**: Comprehensive JUnit 5 test suite covering:
  - Factory projection from events
  - Computed methods (efficiency, duration, isLongHaul)
  - Edge cases (zero distance, no fuel, boundary conditions)
  - Mapper transformation
  - UUID and timestamp formatting

All public methods include Javadoc. Immutability is enforced through Java 21 records.

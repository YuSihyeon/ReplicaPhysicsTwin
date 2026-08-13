#include "Bridge/MuJoCoBridgeTypes.h"

#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	bool ReadVector(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, int32 ExpectedSize, TArray<double>& OutValues, FString& OutError)
	{
		const TArray<TSharedPtr<FJsonValue>>* JsonValues = nullptr;
		if (!Object->TryGetArrayField(FieldName, JsonValues) || JsonValues == nullptr || JsonValues->Num() != ExpectedSize)
		{
			OutError = FString::Printf(TEXT("field '%s' must contain %d numbers"), FieldName, ExpectedSize);
			return false;
		}

		OutValues.Reset(ExpectedSize);
		for (const TSharedPtr<FJsonValue>& JsonValue : *JsonValues)
		{
			double Number = 0.0;
			if (!JsonValue.IsValid() || !JsonValue->TryGetNumber(Number) || !FMath::IsFinite(Number))
			{
				OutError = FString::Printf(TEXT("field '%s' contains a non-finite number"), FieldName);
				return false;
			}
			OutValues.Add(Number);
		}
		return true;
	}

	bool ReadRequiredNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, double& OutNumber, FString& OutError)
	{
		if (!Object->TryGetNumberField(FieldName, OutNumber) || !FMath::IsFinite(OutNumber))
		{
			OutError = FString::Printf(TEXT("field '%s' must be a finite number"), FieldName);
			return false;
		}
		return true;
	}

	bool ReadOptionalNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, double& OutNumber, FString& OutError)
	{
		if (!Object->HasField(FieldName))
		{
			return true;
		}
		return ReadRequiredNumber(Object, FieldName, OutNumber, OutError);
	}

	bool ReadOptionalVector(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, int32 ExpectedSize, TArray<double>& OutValues, FString& OutError)
	{
		if (!Object->HasField(FieldName))
		{
			return true;
		}
		return ReadVector(Object, FieldName, ExpectedSize, OutValues, OutError);
	}
}

FTransform FMuJoCoObjectState::ToUnrealTransform() const
{
	return FTransform(Rotation, PositionM * 100.0f);
}

bool FMuJoCoStateMessage::ParseLine(const FString& JsonLine, FMuJoCoStateMessage& OutMessage, FString* OutError)
{
	FString LocalError;
	FString& Error = OutError != nullptr ? *OutError : LocalError;
	Error.Reset();

	TSharedPtr<FJsonObject> RootObject;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonLine);
	if (!FJsonSerializer::Deserialize(Reader, RootObject) || !RootObject.IsValid())
	{
		Error = TEXT("message is not a JSON object");
		return false;
	}

	FString Type;
	if (!RootObject->TryGetStringField(TEXT("type"), Type) || Type != TEXT("state"))
	{
		Error = TEXT("message type must be 'state'");
		return false;
	}

	double SchemaVersion = 0.0;
	if (!ReadRequiredNumber(RootObject, TEXT("schema_version"), SchemaVersion, Error)
		|| (SchemaVersion != 1.0 && SchemaVersion != 2.0))
	{
		Error = TEXT("schema_version must be 1 or 2");
		return false;
	}

	double SeqNumber = 0.0;
	if (!ReadRequiredNumber(RootObject, TEXT("seq"), SeqNumber, Error) || SeqNumber < 0.0 || FMath::FloorToDouble(SeqNumber) != SeqNumber)
	{
		Error = TEXT("seq must be a non-negative integer");
		return false;
	}

	double SimTime = 0.0;
	if (!ReadRequiredNumber(RootObject, TEXT("sim_time"), SimTime, Error) || SimTime < 0.0)
	{
		Error = TEXT("sim_time must be a non-negative number");
		return false;
	}

	FString Units;
	FString UpAxis;
	if (!RootObject->TryGetStringField(TEXT("units"), Units) || Units != TEXT("meter"))
	{
		Error = TEXT("state units must be 'meter'");
		return false;
	}
	if (!RootObject->TryGetStringField(TEXT("up_axis"), UpAxis) || UpAxis != TEXT("Z"))
	{
		Error = TEXT("state up_axis must be 'Z'");
		return false;
	}
	FString PhysicsAuthority;
	FString SceneId;
	if (SchemaVersion >= 2.0)
	{
		if (!RootObject->TryGetStringField(TEXT("physics_authority"), PhysicsAuthority) || PhysicsAuthority != TEXT("MuJoCo"))
		{
			Error = TEXT("schema v2 physics_authority must be 'MuJoCo'");
			return false;
		}
		if (!RootObject->TryGetStringField(TEXT("scene_id"), SceneId) || SceneId.IsEmpty())
		{
			Error = TEXT("schema v2 scene_id must be non-empty");
			return false;
		}
	}

	const TArray<TSharedPtr<FJsonValue>>* JsonObjects = nullptr;
	if (!RootObject->TryGetArrayField(TEXT("objects"), JsonObjects) || JsonObjects == nullptr)
	{
		Error = TEXT("objects must be an array");
		return false;
	}

	FMuJoCoStateMessage Parsed;
	Parsed.SchemaVersion = static_cast<int32>(SchemaVersion);
	Parsed.Seq = static_cast<int64>(SeqNumber);
	Parsed.SimTime = SimTime;
	Parsed.SceneId = SceneId;
	Parsed.PhysicsAuthority = PhysicsAuthority;
	for (const TSharedPtr<FJsonValue>& JsonValue : *JsonObjects)
	{
		const TSharedPtr<FJsonObject>* ObjectPtr = nullptr;
		if (!JsonValue.IsValid() || !JsonValue->TryGetObject(ObjectPtr) || ObjectPtr == nullptr || !ObjectPtr->IsValid())
		{
			Error = TEXT("each object entry must be an object");
			return false;
		}

		const TSharedPtr<FJsonObject>& Object = *ObjectPtr;
		FMuJoCoObjectState State;
		if (!Object->TryGetStringField(TEXT("id"), State.ObjectId) || State.ObjectId.IsEmpty())
		{
			Error = TEXT("object id must be a non-empty string");
			return false;
		}
		double SourceObjectId = -1.0;
		if (!ReadOptionalNumber(Object, TEXT("source_object_id"), SourceObjectId, Error))
		{
			return false;
		}
		if (Object->HasField(TEXT("source_object_id")))
		{
			if (SourceObjectId < 0.0 || FMath::FloorToDouble(SourceObjectId) != SourceObjectId)
			{
				Error = TEXT("source_object_id must be a non-negative integer");
				return false;
			}
			State.SourceObjectId = static_cast<int32>(SourceObjectId);
			State.bHasSourceObjectId = true;
		}
		Object->TryGetStringField(TEXT("role"), State.Role);

		TArray<double> Position;
		TArray<double> QuaternionWxyz;
		TArray<double> LinearVelocity;
		TArray<double> AngularVelocity;
		if (!ReadVector(Object, TEXT("position_m"), 3, Position, Error)
			|| !ReadVector(Object, TEXT("quaternion_wxyz"), 4, QuaternionWxyz, Error)
			|| !ReadVector(Object, TEXT("linear_velocity_mps"), 3, LinearVelocity, Error)
			|| !ReadVector(Object, TEXT("angular_velocity_rps"), 3, AngularVelocity, Error))
		{
			return false;
		}

		State.PositionM = FVector(Position[0], Position[1], Position[2]);
		State.Rotation = FQuat(QuaternionWxyz[1], QuaternionWxyz[2], QuaternionWxyz[3], QuaternionWxyz[0]);
		State.Rotation.Normalize();
		State.LinearVelocityMps = FVector(LinearVelocity[0], LinearVelocity[1], LinearVelocity[2]);
		State.AngularVelocityRps = FVector(AngularVelocity[0], AngularVelocity[1], AngularVelocity[2]);

		const TArray<TSharedPtr<FJsonValue>>* JsonDeformedVertices = nullptr;
		if (Object->TryGetArrayField(TEXT("deformed_vertices_m"), JsonDeformedVertices)
			&& JsonDeformedVertices != nullptr)
		{
			if (JsonDeformedVertices->Num() == 0 || JsonDeformedVertices->Num() > 10000)
			{
				Error = TEXT("deformed_vertices_m must contain between 1 and 10000 vertices");
				return false;
			}
			for (const TSharedPtr<FJsonValue>& VertexValue : *JsonDeformedVertices)
			{
				const TArray<TSharedPtr<FJsonValue>>* VertexValues = nullptr;
				if (!VertexValue.IsValid() || !VertexValue->TryGetArray(VertexValues) || VertexValues == nullptr || VertexValues->Num() != 3)
				{
					Error = TEXT("each deformed_vertices_m entry must contain exactly 3 numbers");
					return false;
				}
				double Components[3] = {0.0, 0.0, 0.0};
				for (int32 ComponentIndex = 0; ComponentIndex < 3; ++ComponentIndex)
				{
					if (!(*VertexValues)[ComponentIndex].IsValid()
						|| !(*VertexValues)[ComponentIndex]->TryGetNumber(Components[ComponentIndex])
						|| !FMath::IsFinite(Components[ComponentIndex]))
					{
						Error = TEXT("deformed_vertices_m contains a non-finite number");
						return false;
					}
				}
				State.DeformedVerticesM.Add(FVector(Components[0], Components[1], Components[2]));
			}
			State.bHasDeformedVertices = true;
		}

		const TArray<TSharedPtr<FJsonValue>>* JsonContacts = nullptr;
		if (Object->TryGetArrayField(TEXT("contacts"), JsonContacts) && JsonContacts != nullptr)
		{
			for (const TSharedPtr<FJsonValue>& ContactValue : *JsonContacts)
			{
				const TSharedPtr<FJsonObject> ContactObject = ContactValue.IsValid() ? ContactValue->AsObject() : nullptr;
				if (!ContactObject.IsValid())
				{
					Error = TEXT("contact entry must be an object");
					return false;
				}
				FMuJoCoContact Contact;
				if (!ContactObject->TryGetStringField(TEXT("other_id"), Contact.OtherId) || Contact.OtherId.IsEmpty())
				{
					Error = TEXT("contact other_id must be non-empty");
					return false;
				}
				TArray<double> Force;
				if (!ReadVector(ContactObject, TEXT("force_n"), 3, Force, Error))
				{
					return false;
				}
				Contact.ForceN = FVector(Force[0], Force[1], Force[2]);
				if (!ReadOptionalNumber(ContactObject, TEXT("distance_m"), Contact.DistanceM, Error))
				{
					return false;
				}
				State.Contacts.Add(MoveTemp(Contact));
			}
		}

		const TSharedPtr<FJsonObject>* PropertiesObject = nullptr;
		if (Object->TryGetObjectField(TEXT("properties"), PropertiesObject) && PropertiesObject != nullptr && PropertiesObject->IsValid())
		{
			State.bHasProperties = true;
			TArray<double> Values;
			if (!ReadOptionalVector(*PropertiesObject, TEXT("size_m"), 3, Values, Error))
			{
				return false;
			}
			if (Values.Num() == 3)
			{
				State.Properties.SizeM = FVector(Values[0], Values[1], Values[2]);
			}
			Values.Reset();
			if (!ReadOptionalVector(*PropertiesObject, TEXT("inertia_diagonal_kg_m2"), 3, Values, Error))
			{
				return false;
			}
			if (Values.Num() == 3)
			{
				State.Properties.InertiaDiagonalKgM2 = FVector(Values[0], Values[1], Values[2]);
			}
			if (!ReadOptionalNumber(*PropertiesObject, TEXT("mass_kg"), State.Properties.MassKg, Error))
			{
				return false;
			}
			const TSharedPtr<FJsonObject>* FrictionObject = nullptr;
			if ((*PropertiesObject)->TryGetObjectField(TEXT("friction"), FrictionObject) && FrictionObject != nullptr && FrictionObject->IsValid())
			{
				double Sliding = 0.0;
				double Torsional = 0.0;
				double Rolling = 0.0;
				if (!ReadOptionalNumber(*FrictionObject, TEXT("sliding"), Sliding, Error)
					|| !ReadOptionalNumber(*FrictionObject, TEXT("torsional"), Torsional, Error)
					|| !ReadOptionalNumber(*FrictionObject, TEXT("rolling"), Rolling, Error))
				{
					return false;
				}
				State.Properties.Friction = FVector(Sliding, Torsional, Rolling);
			}
			bool bMovable = false;
			if ((*PropertiesObject)->TryGetBoolField(TEXT("movable"), bMovable))
			{
				State.Properties.bMovable = bMovable;
			}
		}
		Parsed.Objects.Add(MoveTemp(State));
	}

	OutMessage = MoveTemp(Parsed);
	return true;
}

bool FMuJoCoStateMessage::ShouldApplySequence(int64 LastAppliedSeq, int64 CandidateSeq)
{
	return CandidateSeq > LastAppliedSeq;
}

import { NextResponse } from "next/server";
import bcrypt from "bcrypt";

import { connectToDatabase } from "@/lib/mongodb";
import { UserModel } from "@/models/User";
import { validateSignupInput } from "@/lib/validation";

const SALT_ROUNDS = 12;

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);

  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: "Invalid request body." }, { status: 400 });
  }

  const { valid, errors } = validateSignupInput(body);
  if (!valid) {
    return NextResponse.json({ errors }, { status: 400 });
  }

  const name = String(body.name).trim();
  const email = String(body.email).trim().toLowerCase();
  const password = String(body.password);

  await connectToDatabase();

  const existingUser = await UserModel.findOne({ email });
  if (existingUser) {
    return NextResponse.json(
      { errors: { email: "An account with this email already exists." } },
      { status: 409 }
    );
  }

  const passwordHash = await bcrypt.hash(password, SALT_ROUNDS);

  const user = await UserModel.create({ name, email, passwordHash });

  // Deliberately return only non-sensitive fields — passwordHash must never
  // reach the browser, even though the schema's `select: false` already
  // means `user.passwordHash` isn't populated on this document.
  return NextResponse.json(
    { id: user._id.toString(), name: user.name, email: user.email },
    { status: 201 }
  );
}
